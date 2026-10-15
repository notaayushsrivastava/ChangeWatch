"""Safe, versioned Alembic migrations for local setup and explicit recovery.

Production/serverless startup migration is disabled by default. If enabled explicitly,
it requires a direct PostgreSQL connection, serializes concurrent cold starts with a
PostgreSQL advisory lock, and refuses to initialize over an unversioned existing schema.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from app.config import settings

# Stable application-specific lock id pair, shared by every process using this helper.
_ADVISORY_LOCK_CLASS = 1381258095
_ADVISORY_LOCK_OBJECT = 5512025
_REPO_ROOT = Path(__file__).resolve().parents[1]


def validate_initial_schema(tables: set[str]) -> None:
    """Never apply the initial revision over a pre-existing, unversioned schema."""
    existing = set(tables) - {"alembic_version"}
    if "alembic_version" not in tables and existing:
        raise RuntimeError(
            "Refusing to apply the initial database migration because the database "
            "contains unversioned tables: "
            + ", ".join(sorted(existing))
            + ". Inspect the schema and baseline it deliberately before migrating."
        )


def apply_database_migrations(
    database_url: str | None = None,
    *,
    require_direct_postgres: bool = False,
) -> None:
    """Apply reviewed Alembic revisions, using the exact same connection for locking and DDL."""
    if require_direct_postgres:
        url = settings.MIGRATION_DATABASE_URL
        if not url:
            raise RuntimeError(
                "MIGRATION_DATABASE_URL is required when startup migrations are explicitly enabled."
            )
    else:
        url = database_url or settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL

    if require_direct_postgres:
        if not url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Startup migrations require a PostgreSQL URL using psycopg 3.")
        if "-pooler." in url:
            raise RuntimeError(
                "Startup migrations require Neon’s direct/unpooled connection, not the pooler URL."
            )

    engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            lock_held = False
            try:
                if connection.dialect.name == "postgresql":
                    connection.exec_driver_sql(
                        "SELECT pg_advisory_lock(%s, %s)",
                        (_ADVISORY_LOCK_CLASS, _ADVISORY_LOCK_OBJECT),
                    ).scalar_one()
                    connection.commit()
                    lock_held = True

                tables = set(inspect(connection).get_table_names())
                # End the inspection query's implicit transaction before Alembic starts.
                connection.rollback()
                validate_initial_schema(tables)

                alembic_config = Config(str(_REPO_ROOT / "alembic.ini"))
                alembic_config.set_main_option(
                    "script_location", str(_REPO_ROOT / "migrations")
                )
                alembic_config.attributes["connection"] = connection
                command.upgrade(alembic_config, "head")
                connection.commit()
            finally:
                if connection.in_transaction():
                    connection.rollback()
                if lock_held:
                    try:
                        connection.exec_driver_sql(
                            "SELECT pg_advisory_unlock(%s, %s)",
                            (_ADVISORY_LOCK_CLASS, _ADVISORY_LOCK_OBJECT),
                        ).scalar_one()
                        connection.commit()
                    except Exception:
                        # Closing this direct connection also releases any session lock.
                        connection.invalidate()
    finally:
        engine.dispose()
