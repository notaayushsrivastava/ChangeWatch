import pytest

from app.database_migrations import validate_initial_schema


def test_empty_database_is_safe_for_initial_migration():
    validate_initial_schema(set())


def test_alembic_versioned_database_is_safe_to_upgrade():
    validate_initial_schema({"alembic_version", "users"})


def test_existing_unversioned_schema_is_refused():
    with pytest.raises(RuntimeError, match="unversioned tables: users"):
        validate_initial_schema({"users", "monitors"})
