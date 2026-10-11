import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db import Base


class Version(Base):
    __tablename__ = "versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_id = Column(String(36), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    check_run_id = Column(String(36), ForeignKey("check_runs.id", ondelete="SET NULL"), nullable=True)

    version_number = Column(Integer, default=1, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    normalized_text = Column(Text, nullable=False)
    screenshot_artifact_key = Column(String(255), nullable=True)
    raw_text_artifact_key = Column(String(255), nullable=True)

    reason = Column(String(30), default="baseline", nullable=False)  # baseline, content_changed, visual_changed
    capture_metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    monitor = relationship("Monitor", back_populates="versions")
    check_run = relationship("CheckRun", back_populates="version")
    alert_events = relationship("AlertEvent", back_populates="version")

    @property
    def capture_metadata(self) -> dict:
        try:
            return json.loads(self.capture_metadata_json) if self.capture_metadata_json else {}
        except Exception:
            return {}

    @capture_metadata.setter
    def capture_metadata(self, val: dict):
        self.capture_metadata_json = json.dumps(val or {})
