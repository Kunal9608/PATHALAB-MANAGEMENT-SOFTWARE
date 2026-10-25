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
    Security Architecture & E2EE Boundary:
    - File content is encrypted client-side in the browser (AES-256-GCM); the server receives ONLY ciphertext bytes.
    - True Zero-Knowledge server storage: The server does NOT possess the vault key and cannot decrypt or parse the content.
    - The server does NOT claim to scan ciphertext with plaintext antivirus scanners (preserving true E2EE).
    - Enforces:
        1. Strict Administrator-only role gate
        2. Streaming read bounded to 15MB (DoS prevention)
        3. Encryption envelope metadata schema validation
        4. Strict isolation: stored at vault/{admin_id}/{item_id}.enc
        5. Zero execution/parsing of ciphertext bytes
    """
    # 1. Parse and validate encryption metadata envelope
    try:
        metadata_dict = json.loads(encryption_metadata) if encryption_metadata else {}
        if not isinstance(metadata_dict, dict):
            raise ValueError("encryption_metadata must be a JSON object")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid encryption_metadata JSON envelope")

    # 2. Bounded streaming read (max 15MB)
    from backend.app.core.upload_security import read_upload_file_bounded
    max_vault_size = 15 * 1024 * 1024  # 15 MB
    try:
        ciphertext_bytes = await read_upload_file_bounded(ciphertext_file, max_size=max_vault_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_size_bytes = len(ciphertext_bytes)
    if file_size_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded ciphertext document is empty (0 bytes)")

    # 3. Validate metadata constraints
    if not title_encrypted or len(title_encrypted.strip()) == 0:
        raise HTTPException(status_code=400, detail="Encrypted title is required")
    if len(title_encrypted) > 4096:
        raise HTTPException(status_code=400, detail="Encrypted title length exceeds safe limit")

    clean_category = (category or "General").strip()[:50]

    return vault_service.create_document(
        db=db,
        admin_id=current_user.id,
        title_encrypted=title_encrypted,
        original_filename_encrypted=original_filename_encrypted,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        ciphertext_bytes=ciphertext_bytes,
        encryption_metadata=metadata_dict,
        category=clean_category
    )


@router.get("/{item_id}", response_model=VaultItemResponse)
def get_vault_item(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Retrieve metadata of a specific vault item belonging strictly to the current admin."""
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
    Access Control & Safe Download:
    - Restricted to the owning administrator only (cross-admin access blocked with 404/403).
    - Client decrypts ciphertext in-memory using its local vault key.
    - Protected with nosniff, CSP default-src 'none', X-Frame-Options DENY, and no-store caching.
    """
    item, ciphertext_bytes = vault_service.download_document(db, admin_id=current_user.id, item_id=item_id)
    return Response(
        content=ciphertext_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{item_id}.enc"',
            "Content-Type": "application/octet-stream",
            "X-Item-Type": item.item_type,
            "X-Encrypted-Original-Mime": item.mime_type or "application/octet-stream",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none';",
            "X-Frame-Options": "DENY",
            "Cache-Control": "private, no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
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
