import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db import Base


class NumericObservation(Base):
    __tablename__ = "numeric_observations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_id = Column(String(36), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Float, nullable=False)
    raw_text = Column(String(100), nullable=False)
    unit = Column(String(20), nullable=True)  # e.g., '$', 'users', '%'
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    monitor = relationship("Monitor", back_populates="numeric_observations")
