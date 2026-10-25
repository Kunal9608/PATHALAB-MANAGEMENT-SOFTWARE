import logging
import uuid
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.app.models.admin_vault_item import AdminVaultItem
from backend.app.schemas.vault import VaultNoteCreate, VaultItemUpdate
from backend.app.core.storage import upload_file_bytes, download_file_bytes, delete_file_object
from backend.app.services import audit_service

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    "application/octet-stream",
}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB limit for encrypted vault documents


def list_items(db: Session, admin_id: uuid.UUID, category: Optional[str] = None) -> List[AdminVaultItem]:
    """Retrieve all vault items belonging strictly to the authenticated admin."""
    query = db.query(AdminVaultItem).filter(AdminVaultItem.admin_id == admin_id)
    if category and category.strip() and category.strip().lower() != "all":
        query = query.filter(AdminVaultItem.category == category.strip())
    return query.order_by(AdminVaultItem.created_at.desc()).all()


def get_item(db: Session, admin_id: uuid.UUID, item_id: uuid.UUID) -> Optional[AdminVaultItem]:
    """Retrieve a single vault item with strict per-admin isolation."""
    return db.query(AdminVaultItem).filter(
        AdminVaultItem.id == item_id,
        AdminVaultItem.admin_id == admin_id
    ).first()


def create_note(db: Session, admin_id: uuid.UUID, payload: VaultNoteCreate) -> AdminVaultItem:
    """Store an encrypted personal note for the admin."""
    item_id = uuid.uuid4()
    item = AdminVaultItem(
        id=item_id,
        admin_id=admin_id,
        item_type="note",
        category=payload.category or "General",
        title_encrypted=payload.title_encrypted,
        content_encrypted=payload.content_encrypted,
        encryption_metadata=payload.encryption_metadata or {},
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    audit_service.log(
        db,
        action="VAULT_NOTE_CREATED",
        actor_user_id=admin_id,
        entity_type="AdminVaultItem",
        entity_id=item_id,
        after={"item_type": "note", "category": item.category}
    )
    return item


def create_document(
    db: Session,
    admin_id: uuid.UUID,
    title_encrypted: str,
    original_filename_encrypted: Optional[str],
    mime_type: Optional[str],
    file_size_bytes: int,
    ciphertext_bytes: bytes,
    encryption_metadata: dict,
    category: Optional[str] = "General"
) -> AdminVaultItem:
    """Store an encrypted document in Joy S3 with metadata in DB."""
    if file_size_bytes > MAX_FILE_SIZE_BYTES or len(ciphertext_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Ciphertext exceeds maximum allowed file size of 15MB")

    effective_mime = mime_type.lower() if mime_type else "application/octet-stream"
    if effective_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported document MIME type: {effective_mime}")

    item_id = uuid.uuid4()
    storage_folder = f"vault/{admin_id}"
    storage_filename = f"{item_id}.enc"

    # Persist encrypted bytes to Joy S3
    try:
        storage_path = upload_file_bytes(
            file_bytes=ciphertext_bytes,
            filename=storage_filename,
            content_type="application/octet-stream",
            folder=storage_folder
        )
    except Exception as e:
        logger.error(f"Failed to upload encrypted vault document to storage: {e}")
        raise HTTPException(status_code=500, detail="Failed to persist encrypted document to file storage")

    meta = dict(encryption_metadata or {})
    if original_filename_encrypted:
        meta["filename_encrypted"] = original_filename_encrypted

    item = AdminVaultItem(
        id=item_id,
        admin_id=admin_id,
        item_type="document",
        category=category or "General",
        title_encrypted=title_encrypted,
        mime_type=effective_mime,
        file_size_bytes=file_size_bytes,
        storage_path=storage_path,
        encryption_metadata=meta
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    audit_service.log(
        db,
        action="VAULT_DOCUMENT_UPLOADED",
        actor_user_id=admin_id,
        entity_type="AdminVaultItem",
        entity_id=item_id,
        after={"item_type": "document", "file_size_bytes": file_size_bytes, "category": item.category}
    )
    return item


def download_document(db: Session, admin_id: uuid.UUID, item_id: uuid.UUID) -> Tuple[AdminVaultItem, bytes]:
    """Retrieve encrypted document ciphertext bytes for client-side decryption."""
    item = get_item(db, admin_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Vault item not found")

    if item.item_type != "document" or not item.storage_path:
        raise HTTPException(status_code=400, detail="Selected item is not a stored document")

    try:
        ciphertext_bytes = download_file_bytes(item.storage_path)
        return item, ciphertext_bytes
    except Exception as e:
        logger.error(f"Error downloading vault document ciphertext for {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document ciphertext from storage")


def update_item(db: Session, admin_id: uuid.UUID, item_id: uuid.UUID, payload: VaultItemUpdate) -> AdminVaultItem:
    """Update encrypted title, category, or note content."""
    item = get_item(db, admin_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Vault item not found")

    if payload.title_encrypted is not None:
        item.title_encrypted = payload.title_encrypted
    if payload.category is not None:
        item.category = payload.category
    if payload.content_encrypted is not None and item.item_type == "note":
        item.content_encrypted = payload.content_encrypted
    if payload.encryption_metadata is not None:
        item.encryption_metadata = payload.encryption_metadata

    db.commit()
    db.refresh(item)

    audit_service.log(
        db,
        action="VAULT_ITEM_UPDATED",
        actor_user_id=admin_id,
        entity_type="AdminVaultItem",
        entity_id=item_id,
        after={"item_type": item.item_type, "category": item.category}
    )
    return item


def delete_item(db: Session, admin_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    """
    Perform cryptographic erasure and deletion:
    1. Delete binary ciphertext from Joy S3 if a document.
    2. Delete row from admin_vault_items table.
    3. Minimal non-sensitive audit logging.
    """
    item = get_item(db, admin_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Vault item not found")

    if item.storage_path:
        try:
            delete_file_object(item.storage_path)
            logger.info(f"Deleted vault ciphertext object from storage: {item.storage_path}")
        except Exception as e:
            logger.warning(f"Storage deletion warning for vault item {item_id}: {e}")

    db.delete(item)
    db.commit()

    audit_service.log(
        db,
        action="VAULT_ITEM_DELETED",
        actor_user_id=admin_id,
        entity_type="AdminVaultItem",
        entity_id=item_id,
        after={"deleted": True}
    )
    return True
