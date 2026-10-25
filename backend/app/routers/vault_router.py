import json
import logging
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Response, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.dependencies import require_admin
from backend.app.models.user import User
from backend.app.schemas.vault import VaultNoteCreate, VaultItemUpdate, VaultItemResponse
from backend.app.services import vault_service

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field

router = APIRouter(prefix="/admin/vault", tags=["Admin Important Documents Vault"])


class VaultUnlockVerifySchema(BaseModel):
    password: str = Field(..., min_length=1)


@router.post("/verify-unlock")
def verify_vault_unlock(
    payload: VaultUnlockVerifySchema,
    current_user: User = Depends(require_admin),
):
    """
    Verify the administrator's account password to unlock the private vault.
    Ensures the vault password is the admin's account password.
    """
    from backend.app.core.security import verify_password
    is_valid, _ = verify_password(payload.password, current_user.password_hash)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Incorrect account password")
    return {"status": "ok", "message": "Password verified successfully"}


@router.get("", response_model=List[VaultItemResponse])
def list_vault_items(
    category: Optional[str] = Query(None, description="Optional category filter"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all encrypted vault items for the authenticated admin only.
    Strict creator-level ownership: Admin A sees only Admin A's items.
    """
    return vault_service.list_items(db, admin_id=current_user.id, category=category)


@router.post("/notes", response_model=VaultItemResponse, status_code=status.HTTP_201_CREATED)
def create_vault_note(
    payload: VaultNoteCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Store an encrypted note for the authenticated admin.
    Client encrypts title and content before transmission.
    """
    return vault_service.create_note(db, admin_id=current_user.id, payload=payload)


@router.post("/documents", response_model=VaultItemResponse, status_code=status.HTTP_201_CREATED)
async def upload_vault_document(
    ciphertext_file: UploadFile = File(...),
    title_encrypted: str = Form(...),
    original_filename_encrypted: Optional[str] = Form(None),
    mime_type: Optional[str] = Form("application/octet-stream"),
    category: Optional[str] = Form("General"),
    encryption_metadata: str = Form("{}"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Upload an encrypted document to the private admin vault.
    File content is encrypted client-side; only ciphertext bytes are transmitted.
    Stored securely in Joy S3 with path isolated to vault/{admin_id}/{item_id}.enc.
    """
    try:
        metadata_dict = json.loads(encryption_metadata) if encryption_metadata else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid encryption_metadata JSON")

    ciphertext_bytes = await ciphertext_file.read()
    file_size_bytes = len(ciphertext_bytes)

    if file_size_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded document is empty")

    return vault_service.create_document(
        db=db,
        admin_id=current_user.id,
        title_encrypted=title_encrypted,
        original_filename_encrypted=original_filename_encrypted,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        ciphertext_bytes=ciphertext_bytes,
        encryption_metadata=metadata_dict,
        category=category or "General"
    )


@router.get("/{item_id}", response_model=VaultItemResponse)
def get_vault_item(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Retrieve metadata of a specific vault item belonging to the current admin."""
    item = vault_service.get_item(db, admin_id=current_user.id, item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Vault item not found")
    return item


@router.get("/{item_id}/content")
def download_vault_document_ciphertext(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Download raw ciphertext bytes of an encrypted vault document.
    Client decrypts the ciphertext in-memory using its local vault key.
    """
    item, ciphertext_bytes = vault_service.download_document(db, admin_id=current_user.id, item_id=item_id)
    return Response(
        content=ciphertext_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{item_id}.enc"',
            "X-Item-Type": item.item_type,
            "X-Encrypted-Original-Mime": item.mime_type or "application/octet-stream"
        }
    )


@router.put("/{item_id}", response_model=VaultItemResponse)
def update_vault_item(
    item_id: uuid.UUID,
    payload: VaultItemUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update title, category, or note content of an existing vault item."""
    return vault_service.update_item(db, admin_id=current_user.id, item_id=item_id, payload=payload)


@router.delete("/{item_id}", status_code=status.HTTP_200_OK)
def delete_vault_item(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Permanently delete a vault item (cryptographic erasure).
    Removes ciphertext from Joy S3 and deletes the database record.
    """
    success = vault_service.delete_item(db, admin_id=current_user.id, item_id=item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Vault item not found")
    return {"message": "Vault item permanently deleted"}
