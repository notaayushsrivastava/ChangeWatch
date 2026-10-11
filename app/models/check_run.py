import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db import Base


class CheckRun(Base):
    __tablename__ = "check_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_id = Column(String(36), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_for = Column(DateTime, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime, nullable=True)

    status = Column(String(20), default="running", nullable=False)  # queued, running, ok, error, blocked, cancelled
    attempt_number = Column(Integer, default=1, nullable=False)
    http_status = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True)
    changed = Column(Boolean, default=False, nullable=False)

    failure_code = Column(String(50), nullable=True)
    safe_error_message = Column(Text, nullable=True)
    capture_metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    monitor = relationship("Monitor", back_populates="check_runs")
    version = relationship("Version", back_populates="check_run", uselist=False)

    @property
    def capture_metadata(self) -> dict:
        try:
            return json.loads(self.capture_metadata_json) if self.capture_metadata_json else {}
        except Exception:
            return {}

    @capture_metadata.setter
    def capture_metadata(self, val: dict):
        self.capture_metadata_json = json.dumps(val or {})
