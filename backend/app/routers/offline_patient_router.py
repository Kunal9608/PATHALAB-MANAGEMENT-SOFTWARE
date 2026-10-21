"""Offline patient router — isolated API for user-scoped offline registrations and failed cached patient recovery."""
from fastapi import APIRouter, Depends, Query, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import uuid

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, get_idempotency_key
from backend.app.models.user import User
from backend.app.services import offline_patient_service

router = APIRouter(prefix="/offline-patients", tags=["offline-patients"])


@router.post("", status_code=201)
def create_offline_patient(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
    x_temp_ref_id: Optional[str] = Header(None, alias="X-Temp-Ref-ID"),
):
    """
    FR-11 — Enqueue an offline patient registration.
    Durable storage in PostgreSQL guarantees survival across restarts and Redis outages.
    Attempts immediate synchronization. If successful, commits patient and marks SUCCESS.
    If synchronization fails, preserves the record in FAILED state for owner recovery.
    """
    temp_ref_id = payload.get("temp_ref_id") or x_temp_ref_id
    cached_record = offline_patient_service.enqueue_offline_patient(
        db,
        patient_data=payload,
        current_user=current_user,
        idempotency_key=idempotency_key,
        temp_ref_id=temp_ref_id,
    )

    # Process synchronization
    result = offline_patient_service.process_single_registration(db, cached_record, current_user)
    return result


@router.get("/failed")
def list_failed_cached_patients(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    CRITICAL ACCESS-CONTROL:
    Returns FAILED cached registrations belonging strictly to the authenticated creator.
    - Admin A sees only Admin A's failed records.
    - Admin B sees only Admin B's failed records.
    - Staff A sees only Staff A's failed records.
    - Staff B sees only Staff B's failed records.
    - Staff cannot see Admin records.
    - Admin cannot see Staff failed records on this page.
    - Only records in FAILED status are returned.
    """
    return offline_patient_service.list_failed_registrations(
        db, current_user, q=q, page=page, page_size=page_size
    )


@router.get("/{record_id}")
def get_failed_cached_patient(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve single failed cached registration.
    Strictly verifies ownership: returns 404 if not found or owned by another user.
    """
    return offline_patient_service.get_failed_registration(db, record_id, current_user)


@router.post("/{record_id}/retry")
def retry_failed_cached_patient(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retry synchronizing a single failed registration.
    - Confirms authenticated user owns the record.
    - Prevents concurrent duplicate retries.
    - On success: confirms permanent patient ID, marks SUCCESS, removes from failed view.
    - On failure: preserves record, updates retry count and failure reason.
    - Idempotently recovers existing patient if PostgreSQL already committed previously.
    """
    return offline_patient_service.retry_failed_registration(db, record_id, current_user)


@router.post("/recover-stale")
def recover_stale_syncing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recover jobs stuck in SYNCING state due to connection drops or worker restarts."""
    count = offline_patient_service.recover_stale_syncing_jobs(db, max_age_seconds=60)
    return {"recovered_count": count}
