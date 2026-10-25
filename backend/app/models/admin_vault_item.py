"""AdminVaultItem model — durable encrypted storage for Administrator Important Documents & Notes."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, JSON, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.core.db import Base


class AdminVaultItem(Base):
    __tablename__ = "admin_vault_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(String(20), nullable=False, default="document", index=True)  # 'document' | 'note'
    category = Column(String(50), nullable=False, default="general", index=True)
    title_encrypted = Column(Text, nullable=False)
    title_hint = Column(String(100), nullable=True)
    storage_path = Column(String(255), nullable=True)
    content_encrypted = Column(Text, nullable=True)  # For secure notes
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    encryption_metadata = Column(JSON, nullable=False)  # { iv, salt, algorithm, auth_tag }
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    admin = relationship("User", foreign_keys=[admin_id])

    @property
    def original_filename_encrypted(self):
        if isinstance(self.encryption_metadata, dict):
            return self.encryption_metadata.get("filename_encrypted")
        return None
