import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db import Base


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    url = Column(Text, nullable=False)
    interval_minutes = Column(Integer, default=60, nullable=False)
    sensitivity = Column(String(20), default="medium", nullable=False)  # low, medium, high
    state = Column(String(20), default="active", nullable=False)  # active, paused, needs_attention, deleted
    is_active = Column(Boolean, default=True, nullable=False)

    # JSON stored as Text for SQLite / Postgres portability
    include_selectors_json = Column(Text, default="[]", nullable=False)
    ignore_selectors_json = Column(Text, default="[]", nullable=False)
    normalization_rules_json = Column(Text, default="{}", nullable=False)
    notification_preferences_json = Column(Text, default="{}", nullable=False)

    # Bonus features: Keyword filtering & Numeric tracking
    keywords_json = Column(Text, default="[]", nullable=False)
    numeric_selector = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    last_checked_at = Column(DateTime, nullable=True)
    last_changed_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True, index=True)

    last_status = Column(String(20), default="pending", nullable=False)  # pending, ok, error, blocked
    last_error_code = Column(String(50), nullable=True)
    last_error_message = Column(Text, nullable=True)
    last_version_id = Column(String(36), nullable=True)

    user = relationship("User", back_populates="monitors")
    check_runs = relationship("CheckRun", back_populates="monitor", cascade="all, delete-orphan", order_by="desc(CheckRun.created_at)")
    versions = relationship("Version", back_populates="monitor", cascade="all, delete-orphan", order_by="desc(Version.created_at)")
    alert_events = relationship("AlertEvent", back_populates="monitor", cascade="all, delete-orphan")
    numeric_observations = relationship("NumericObservation", back_populates="monitor", cascade="all, delete-orphan", order_by="desc(NumericObservation.recorded_at)")

    @property
    def include_selectors(self) -> list:
        try:
            return json.loads(self.include_selectors_json) if self.include_selectors_json else []
        except Exception:
            return []

    @include_selectors.setter
    def include_selectors(self, value: list):
        self.include_selectors_json = json.dumps(value or [])

    @property
    def ignore_selectors(self) -> list:
        try:
            return json.loads(self.ignore_selectors_json) if self.ignore_selectors_json else []
        except Exception:
            return []

    @ignore_selectors.setter
    def ignore_selectors(self, value: list):
        self.ignore_selectors_json = json.dumps(value or [])

    @property
    def keywords(self) -> list:
        try:
            return json.loads(self.keywords_json) if self.keywords_json else []
        except Exception:
            return []

    @keywords.setter
    def keywords(self, value: list):
        self.keywords_json = json.dumps(value or [])
