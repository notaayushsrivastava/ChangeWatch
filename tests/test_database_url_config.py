from app.config import Settings


def test_standard_neon_url_is_normalized_for_psycopg():
    settings = Settings(
        DATABASE_URL=(
            "postgresql://neondb_owner:example@ep-example-pooler."
            "ap-southeast-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require"
        )
    )

    assert settings.DATABASE_URL.startswith("postgresql+psycopg://")
    assert "channel_binding=require" in settings.DATABASE_URL
    assert "sslmode=require" in settings.DATABASE_URL


def test_postgres_url_scheme_is_normalized_for_psycopg():
    settings = Settings(DATABASE_URL="postgres://user:password@localhost:5432/app")

    assert settings.DATABASE_URL == "postgresql+psycopg://user:password@localhost:5432/app"


def test_sqlite_url_is_unchanged():
    settings = Settings(DATABASE_URL="sqlite:///./changewatch.db")

    assert settings.DATABASE_URL == "sqlite:///./changewatch.db"
