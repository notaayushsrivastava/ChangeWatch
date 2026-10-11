import os
import uuid
from pathlib import Path
from typing import Optional
from app.config import settings


class ArtifactStorage:
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or settings.ARTIFACT_STORAGE_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_screenshot(self, image_bytes: bytes, monitor_id: str, version_id: str) -> str:
        filename = f"{monitor_id}_{version_id}_{uuid.uuid4().hex[:8]}.png"
        path = self.base_dir / filename
        path.write_bytes(image_bytes)
        return filename

    def save_diff_image(self, image_bytes: bytes, monitor_id: str, diff_id: str) -> str:
        filename = f"diff_{monitor_id}_{diff_id}_{uuid.uuid4().hex[:8]}.png"
        path = self.base_dir / filename
        path.write_bytes(image_bytes)
        return filename

    def get_artifact_path(self, filename: str) -> Optional[Path]:
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return None
        path = self.base_dir / filename
        return path if path.exists() else None

    def read_bytes(self, filename: str) -> Optional[bytes]:
        path = self.get_artifact_path(filename)
        return path.read_bytes() if path else None

    def delete_artifact(self, filename: str) -> bool:
        path = self.get_artifact_path(filename)
        if path:
            try:
                path.unlink()
                return True
            except Exception:
                return False
        return False


artifact_storage = ArtifactStorage()
