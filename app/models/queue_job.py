import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text
from app.db import Base


class QueueJob(Base):
    __tablename__ = "queue_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    queue = Column(String(50), default="default", nullable=False, index=True)
    task_type = Column(String(50), nullable=False, index=True)  # check_monitor, deliver_alert, daily_digest
    payload_json = Column(Text, default="{}", nullable=False)

    status = Column(String(20), default="pending", nullable=False, index=True)  # pending, running, completed, failed
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    locked_by = Column(String(64), nullable=True)
    locked_at = Column(DateTime, nullable=True)

    scheduled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    @property
    def payload(self) -> dict:
        try:
            return json.loads(self.payload_json) if self.payload_json else {}
        except Exception:
            return {}

    @payload.setter
    def payload(self, val: dict):
        self.payload_json = json.dumps(val or {})
