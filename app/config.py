import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "changewatch-dev-secret-key-at-least-32-chars-long!"
    APP_BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "sqlite:///./changewatch.db"
    QUEUE_TYPE: str = "database"  # database or redis
    REDIS_URL: str = "redis://localhost:6379/0"

    ARTIFACT_STORAGE_DIR: str = "./data/artifacts"

    BROWSER_NAV_TIMEOUT_SECONDS: int = 30
    BROWSER_CHECK_TIMEOUT_SECONDS: int = 60
    BROWSER_STABILIZATION_MS: int = 1500
    BROWSER_MAX_PAGE_HEIGHT: int = 8000

    EMAIL_PROVIDER: str = "console"  # console, smtp, resend
    EMAIL_FROM: str = "alerts@changewatch.local"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    RESEND_API_KEY: str = ""

    ENCRYPTION_KEY: str = "dGhpc2lzYXZlcnlzZWNyZXRrZXkxMjM0NTY3ODkwMTI="
    LOG_LEVEL: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def artifact_dir_path(self) -> Path:
        p = Path(self.ARTIFACT_STORAGE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
