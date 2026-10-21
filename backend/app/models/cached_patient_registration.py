"""CachedPatientRegistration model — durable storage and state machine for offline registrations."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, JSON, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.core.db import Base


class CachedPatientRegistration(Base):
    __tablename__ = "cached_patient_registrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    temp_ref_id = Column(String(64), nullable=False, unique=True, index=True)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_role = Column(String(20), nullable=False)
    patient_data = Column(JSON, nullable=False)
    # State machine: PENDING -> SYNCING -> FAILED | SUCCESS
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    failure_reason = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    permanent_patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    permanent_patient_code = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    owner = relationship("User", foreign_keys=[owner_id])
    patient = relationship("Patient", foreign_keys=[permanent_patient_id])
