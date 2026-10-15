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
    APP_SECRET_KEY: str = "changewatch-dev-secret-key-at-least-32-chars-long!"  # Development fallback only
    APP_BASE_URL: str = "http://localhost:8000"

    DATABASE_URL: str = "sqlite:///./changewatch.db"
    QUEUE_TYPE: str = "database"  # database or redis
    REDIS_URL: str = "redis://localhost:6379/0"

    ARTIFACT_STORAGE_DIR: str = "./data/artifacts"
    ARTIFACT_STORAGE_BACKEND: str | None = None  # local or s3; defaults to s3 on Vercel
    S3_BUCKET: str = ""
    S3_REGION: str = "auto"
    S3_ENDPOINT_URL: str = ""
    S3_PREFIX: str = "changewatch"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Inline/background behavior is suitable for a single-process local dev server only.
    RUN_INLINE_CHECKS: bool = True
    ENABLE_INLINE_SCHEDULER: bool = True

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
    def is_vercel(self) -> bool:
        return os.getenv("VERCEL", "").lower() in {"1", "true"}

    @property
    def is_production(self) -> bool:
        # Vercel exposes VERCEL_ENV=production on production deployments.
        # Keep previews usable before their database/object-store services exist.
        return self.APP_ENV.lower() == "production" or (
            self.is_vercel and os.getenv("VERCEL_ENV", "").lower() == "production"
        )

    @property
    def run_inline_checks(self) -> bool:
        return self.RUN_INLINE_CHECKS and not self.is_vercel and not self.is_production

    @property
    def artifact_backend(self) -> str:
        configured = (self.ARTIFACT_STORAGE_BACKEND or "").strip().lower()
        return configured or ("s3" if self.is_vercel else "local")

    def validate_production_config(self) -> None:
        """Fail closed instead of using development secrets or ephemeral storage in production."""
        problems = []
        if (
            len(self.APP_SECRET_KEY) < 32
            or self.APP_SECRET_KEY.startswith("changewatch-dev-")
            or self.APP_SECRET_KEY.startswith("change-me-")
        ):
            problems.append("APP_SECRET_KEY must be a unique random secret of at least 32 characters")
        try:
            from cryptography.fernet import Fernet
            Fernet(self.ENCRYPTION_KEY.encode("utf-8"))
            if self.ENCRYPTION_KEY == "dGhpc2lzYXZlcnlzZWNyZXRrZXkxMjM0NTY3ODkwMTI=":
                problems.append("ENCRYPTION_KEY must be generated specifically for this deployment")
        except Exception:
            problems.append("ENCRYPTION_KEY must be a valid, unique Fernet key")
        if not self.DATABASE_URL.lower().startswith("postgresql+psycopg://"):
            problems.append("DATABASE_URL must use managed PostgreSQL with the psycopg driver")
        if self.artifact_backend != "s3" or not self.S3_BUCKET.strip():
            problems.append("Set ARTIFACT_STORAGE_BACKEND=s3 and configure S3_BUCKET for durable artifacts")
        if self.APP_BASE_URL.startswith("http://localhost"):
            problems.append("APP_BASE_URL must be the public HTTPS application URL")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))

    @property
    def artifact_dir_path(self) -> Path:
        p = Path(self.ARTIFACT_STORAGE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
