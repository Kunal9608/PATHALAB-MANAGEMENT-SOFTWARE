"""Test price history — audit trail for every price change."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Numeric, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.core.db import Base


class TestPriceHistory(Base):
    __tablename__ = "test_price_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    test_id = Column(UUID(as_uuid=True), ForeignKey("tests.id", ondelete="CASCADE"), nullable=False, index=True)
    old_price = Column(Numeric(10, 2), nullable=True)
    new_price = Column(Numeric(10, 2), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    test = relationship("Test", back_populates="price_history")
    changed_by_user = relationship("User")
