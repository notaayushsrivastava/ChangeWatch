import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(20), nullable=False)  # email, discord
    label = Column(String(100), nullable=False)
    destination = Column(Text, nullable=False)  # encrypted webhook URL or email address
    is_enabled = Column(Boolean, default=True, nullable=False)

    last_tested_at = Column(DateTime, nullable=True)
    last_delivery_status = Column(String(20), nullable=True)  # success, failure

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="notification_channels")
    deliveries = relationship("AlertDelivery", back_populates="channel", cascade="all, delete-orphan")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_id = Column(String(36), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String(36), ForeignKey("versions.id", ondelete="CASCADE"), nullable=False)
    dedupe_key = Column(String(128), unique=True, index=True, nullable=False)
    summary = Column(Text, nullable=False)
    diff_snippet = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    monitor = relationship("Monitor", back_populates="alert_events")
    version = relationship("Version", back_populates="alert_events")
    deliveries = relationship("AlertDelivery", back_populates="alert_event", cascade="all, delete-orphan")


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_event_id = Column(String(36), ForeignKey("alert_events.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(String(36), ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    dedupe_key = Column(String(128), unique=True, index=True, nullable=False)

    status = Column(String(30), default="queued", nullable=False)  # queued, sent, retryable_failure, permanent_failure
    attempt_count = Column(Integer, default=0, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    provider_error_code = Column(String(50), nullable=True)
    provider_error_message = Column(Text, nullable=True)

    alert_event = relationship("AlertEvent", back_populates="deliveries")
    channel = relationship("NotificationChannel", back_populates="deliveries")
