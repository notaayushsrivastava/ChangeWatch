import uuid
from pathlib import Path
from typing import Optional

from botocore.config import Config

from app.config import settings


class ArtifactStorage:
    """Persistent screenshot storage: local volume for dev/Docker or S3-compatible storage on Vercel."""

    def __init__(self, base_dir: Optional[str] = None):
        self.backend = "local" if base_dir else settings.artifact_backend
        self.base_dir = Path(base_dir or settings.ARTIFACT_STORAGE_DIR)
        self._s3_client = None
        if self.backend == "local":
            self.base_dir.mkdir(parents=True, exist_ok=True)
        elif self.backend != "s3":
            raise ValueError("ARTIFACT_STORAGE_BACKEND must be either 'local' or 's3'")

    def _client(self):
        if not settings.S3_BUCKET.strip():
            raise RuntimeError("S3_BUCKET is required for S3 artifact storage")
        if self._s3_client is None:
            import boto3

            kwargs = {
                "region_name": settings.S3_REGION or None,
                # Neon object storage requires path-style bucket addressing.
                "config": Config(s3={"addressing_style": "path"}),
            }
            if settings.S3_ENDPOINT_URL.strip():
                kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL.strip()
            # Leave credentials to the SDK's role/identity chain unless explicit keys were configured.
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
            self._s3_client = boto3.client("s3", **kwargs)
        return self._s3_client

    @staticmethod
    def _validate_filename(filename: str) -> bool:
        return bool(filename) and filename not in {".", ".."} and "/" not in filename and "\\" not in filename and ".." not in filename

    def _key(self, filename: str) -> str:
        prefix = settings.S3_PREFIX.strip("/")
        return f"{prefix}/{filename}" if prefix else filename

    def _save(self, image_bytes: bytes, filename: str) -> str:
        if self.backend == "s3":
            self._client().put_object(
                Bucket=settings.S3_BUCKET,
                Key=self._key(filename),
                Body=image_bytes,
                ContentType="image/png",
            )
        else:
            (self.base_dir / filename).write_bytes(image_bytes)
        return filename

    def save_screenshot(self, image_bytes: bytes, monitor_id: str, version_id: str) -> str:
        filename = f"{monitor_id}_{version_id}_{uuid.uuid4().hex[:8]}.png"
        return self._save(image_bytes, filename)

    def save_diff_image(self, image_bytes: bytes, monitor_id: str, diff_id: str) -> str:
        filename = f"diff_{monitor_id}_{diff_id}_{uuid.uuid4().hex[:8]}.png"
        return self._save(image_bytes, filename)

    def exists(self, filename: str) -> bool:
        if not self._validate_filename(filename):
            return False
        if self.backend == "local":
            return (self.base_dir / filename).is_file()
        try:
            self._client().head_object(Bucket=settings.S3_BUCKET, Key=self._key(filename))
            return True
        except Exception as exc:
            # A missing artifact is normal. Other S3 errors should not masquerade as a hit.
            response = getattr(exc, "response", {}) or {}
            code = str(response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            if isinstance(exc, RuntimeError):
                raise
            raise

    def get_artifact_path(self, filename: str) -> Optional[Path]:
        """Return a local path only; object-store artifacts must be accessed via read_bytes()."""
        if self.backend != "local" or not self._validate_filename(filename):
            return None
        path = self.base_dir / filename
        return path if path.is_file() else None

    def read_bytes(self, filename: str) -> Optional[bytes]:
        if not self._validate_filename(filename):
            return None
        if self.backend == "local":
            path = self.get_artifact_path(filename)
            return path.read_bytes() if path else None
        try:
            response = self._client().get_object(Bucket=settings.S3_BUCKET, Key=self._key(filename))
            return response["Body"].read()
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            code = str(response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def delete_artifact(self, filename: str) -> bool:
        if not self._validate_filename(filename):
            return False
        if self.backend == "s3":
            self._client().delete_object(Bucket=settings.S3_BUCKET, Key=self._key(filename))
            return True
        path = self.get_artifact_path(filename)
        if path:
            path.unlink()
            return True
        return False


artifact_storage = ArtifactStorage()
