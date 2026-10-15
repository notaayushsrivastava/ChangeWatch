"""Safe, versioned Alembic migrations for local setup and explicit recovery.

Production/serverless startup migration is disabled by default. When explicitly enabled
for recovery, it serializes concurrent PostgreSQL startups with a transaction-scoped
advisory lock (compatible with Neon pooling) and refuses to initialize an unversioned,
non-empty schema.
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


def _alembic_config(connection) -> Config:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


def apply_database_migrations(
    database_url: str | None = None,
    *,
    require_postgres: bool = False,
) -> None:
    """Apply reviewed Alembic revisions, serializing PostgreSQL schema changes."""
    url = (
        (settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL)
        if require_postgres
        else (database_url or settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL)
    )
    if require_postgres and not url.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            "One-off startup migrations require managed PostgreSQL using the psycopg 3 driver."
        )

    engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                # Keep lock + schema inspection + all DDL in one transaction. This
                # works with Neon pooled URLs because PgBouncer pins a backend for
                # the transaction, and the xact lock is released automatically.
                with connection.begin():
                    connection.exec_driver_sql(
                        "SELECT pg_advisory_xact_lock(%s, %s)",
                        (_ADVISORY_LOCK_CLASS, _ADVISORY_LOCK_OBJECT),
                    ).scalar_one()
                    tables = set(inspect(connection).get_table_names())
                    validate_initial_schema(tables)
                    command.upgrade(_alembic_config(connection), "head")
            else:
                tables = set(inspect(connection).get_table_names())
                connection.rollback()
                validate_initial_schema(tables)
                command.upgrade(_alembic_config(connection), "head")
    finally:
        engine.dispose()
