"""OTP request model — hashed, single-use, 5-minute TTL."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Enum, DateTime, text, Index
from sqlalchemy.dialects.postgresql import UUID
import enum

from backend.app.core.db import Base


class OtpPurposeEnum(str, enum.Enum):
    login = "login"
    password_reset = "password_reset"
    delete_verify = "delete_verify"
    password_change = "password_change"


class OtpRequest(Base):
    __tablename__ = "otp_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    email = Column(String(255), nullable=False)
    otp_hash = Column(String(255), nullable=False)
    purpose = Column(Enum(OtpPurposeEnum, name="otp_purpose_enum"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    requesting_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_otp_requests_email_purpose", "email", "purpose", "expires_at"),
    )
