from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class VaultNoteCreate(BaseModel):
    title_encrypted: str = Field(..., min_length=1, max_length=1000)
    content_encrypted: str = Field(..., min_length=1)
    category: Optional[str] = Field("General", max_length=50)
    encryption_metadata: Dict[str, Any] = Field(default_factory=dict)


class VaultItemUpdate(BaseModel):
    title_encrypted: Optional[str] = Field(None, max_length=1000)
    content_encrypted: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    encryption_metadata: Optional[Dict[str, Any]] = None


class VaultItemResponse(BaseModel):
    id: UUID
    admin_id: UUID
    item_type: str
    category: Optional[str] = None
    title_encrypted: str
    original_filename_encrypted: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    content_encrypted: Optional[str] = None
    encryption_metadata: Dict[str, Any]
    storage_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
