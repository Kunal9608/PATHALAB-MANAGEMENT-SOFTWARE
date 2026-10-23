"""Offline patient service — durable queue, state machine, idempotency, independent processing, and user isolation."""
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, Any, List

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc

from backend.app.models.cached_patient_registration import CachedPatientRegistration
from backend.app.models.patient import Patient
from backend.app.models.user import User
from backend.app.schemas.patient import PatientCreate
from backend.app.services import patient_service, audit_service
from backend.app.core.redis_client import get_redis

logger = logging.getLogger("akriti.offline_sync")

MAX_RETRIES = 5


def generate_temp_ref_id() -> str:
    """Generate a clean, unambiguous temporary reference ID for offline registrations."""
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_suffix = uuid.uuid4().hex[:6].upper()
    return f"TMP-{now_str}-{random_suffix}"


def sanitize_error_message(exc: Exception) -> str:
    """
    Sanitize internal exceptions to prevent exposing raw SQL, stack traces,
    passwords, tokens, or sensitive patient data in the UI.
    Categorizes into safe, actionable diagnostic reasons.
    """
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            msg = detail.get("message") or str(detail)
            if "duplicate" in msg.lower():
                return "Duplicate patient detected: A registration with this mobile number already exists."
            return msg
        detail_str = str(detail)
        if "duplicate" in detail_str.lower():
            return "Duplicate patient detected: A registration with this mobile number already exists."
        return detail_str

    err_str = str(exc)
    err_lower = err_str.lower()

    if "could not connect" in err_lower or "connection refused" in err_lower or "operationalerror" in err_lower:
        return "Database connection temporarily unavailable. Safe to retry."
    if "duplicate" in err_lower or "unique constraint" in err_lower:
        return "Duplicate patient record detected. Please verify patient identity."
    if "foreign key" in err_lower or "tests not found" in err_lower:
        return "Validation failure: Referenced test or doctor record is invalid or inactive."
    if "valueerror" in err_lower or "discount" in err_lower or "amount" in err_lower or "age" in err_lower:
        # Extract clean value error message if possible
        clean_msg = err_str.replace("ValueError:", "").strip()
        return f"Validation failure: {clean_msg}"
    if "redis" in err_lower:
        return "Queue storage error: Redis unavailable. Saved to durable offline fallback."

    return "Server rejected registration request. Safe to retry."


def enqueue_offline_patient(
    db: Session,
    patient_data: Dict[str, Any],
    current_user: User,
    idempotency_key: Optional[str] = None,
    temp_ref_id: Optional[str] = None,
) -> CachedPatientRegistration:
    """
    Store registration in durable PostgreSQL table with an immutable, server-derived owner.
    Guarantees no data loss even if Redis is completely unavailable or offline.
    """
    if not idempotency_key:
        idempotency_key = f"idem-{uuid.uuid4()}"
    if not temp_ref_id:
        temp_ref_id = generate_temp_ref_id()

    # Check for existing registration with same idempotency key
    existing = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.idempotency_key == idempotency_key
    ).first()

    if existing:
        # Strict ownership verification on existing record
        if existing.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Idempotency key belongs to another user")
        return existing

    # Create new cached registration
    cached_record = CachedPatientRegistration(
        temp_ref_id=temp_ref_id,
        idempotency_key=idempotency_key,
        owner_id=current_user.id,
        owner_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        patient_data=patient_data,
        status="PENDING",
        retry_count=0,
    )
    db.add(cached_record)
    db.commit()
    db.refresh(cached_record)

    # Optional Redis queue notification (user-scoped)
    try:
        r = get_redis()
        if r:
            user_queue_key = f"queue:patient_sync:{current_user.id}"
            r.rpush(user_queue_key, str(cached_record.id))
            r.expire(user_queue_key, 86400)
    except Exception as e:
        logger.debug(f"Redis queue notification skipped ({e}); durable PostgreSQL record safely preserved.")

    return cached_record


def process_single_registration(
    db: Session,
    record: CachedPatientRegistration,
    current_user: User,
) -> Dict[str, Any]:
    """
    Synchronizes a single cached registration independently into PostgreSQL.
    If Patient A succeeds, Patient B fails, Patient C will proceed independently.
    Handles idempotent recovery if PostgreSQL previously committed before a network drop.
    """
    # Verify owner identity
    if record.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Failed cached record not found")

    # If already SUCCESS, return committed patient details
    if record.status == "SUCCESS" and record.permanent_patient_id:
        patient = db.query(Patient).filter(Patient.id == record.permanent_patient_id).first()
        if patient:
            return {
                "status": "SUCCESS",
                "patient_id": str(patient.id),
                "patient_code": patient.patient_code,
                "temp_ref_id": record.temp_ref_id,
                "message": "Patient already synchronized.",
            }

    # Transition to SYNCING
    record.status = "SYNCING"
    record.last_attempt_at = datetime.now(timezone.utc)
    db.commit()

    raw_data = dict(record.patient_data)
    try:
        # Convert date fields if needed
        if "sample_date" in raw_data and isinstance(raw_data["sample_date"], str):
            raw_data["sample_date"] = date.fromisoformat(raw_data["sample_date"])
        if "test_ids" in raw_data and raw_data["test_ids"]:
            raw_data["test_ids"] = [uuid.UUID(str(tid)) for tid in raw_data["test_ids"]]
        if "doctor_id" in raw_data and raw_data["doctor_id"]:
            raw_data["doctor_id"] = uuid.UUID(str(raw_data["doctor_id"]))

        # Check for idempotent recovery: did this exact cached record already commit in PostgreSQL earlier?
        if record.permanent_patient_id:
            committed_existing = db.query(Patient).filter(Patient.id == record.permanent_patient_id).first()
            if committed_existing:
                record.status = "SUCCESS"
                record.permanent_patient_code = committed_existing.patient_code
                record.synced_at = datetime.now(timezone.utc)
                record.failure_reason = None
                record.error_details = None
                db.commit()

                audit_service.log(
                    db, "offline_patient.idempotent_recovery",
                    actor_user_id=current_user.id,
                    entity_type="patient",
                    entity_id=committed_existing.id,
                    after={"temp_ref_id": record.temp_ref_id, "patient_code": committed_existing.patient_code},
                )

                return {
                    "status": "SUCCESS",
                    "patient_id": str(committed_existing.id),
                    "patient_code": committed_existing.patient_code,
                    "temp_ref_id": record.temp_ref_id,
                    "recovered": True,
                }

        # Validate with PatientCreate schema
        pydantic_payload = PatientCreate(**raw_data)

        # Create patient using existing patient service
        result = patient_service.create_patient(
            db,
            pydantic_payload,
            current_user.id,
            background_tasks=None,
            idempotency_key=record.idempotency_key,
        )

        patient_code = result.get("patient_code")
        patient_id = uuid.UUID(result["id"]) if isinstance(result.get("id"), str) else result.get("id")

        # Mark SUCCESS in queue table
        record.status = "SUCCESS"
        record.permanent_patient_id = patient_id
        record.permanent_patient_code = patient_code
        record.synced_at = datetime.now(timezone.utc)
        record.failure_reason = None
        record.error_details = None
        db.commit()

        audit_service.log(
            db, "offline_patient.sync_success",
            actor_user_id=current_user.id,
            entity_type="patient",
            entity_id=patient_id,
            after={"temp_ref_id": record.temp_ref_id, "patient_code": patient_code},
        )

        return {
            "status": "SUCCESS",
            "patient_id": str(patient_id),
            "patient_code": patient_code,
            "temp_ref_id": record.temp_ref_id,
        }

    except Exception as exc:
        db.rollback()
        sanitized_msg = sanitize_error_message(exc)
        logger.warning(f"Offline sync failed for record {record.id} ({record.temp_ref_id}): {exc}")

        # In a fresh sub-transaction, persist the FAILED state and failure diagnostics
        record.status = "FAILED"
        record.failure_reason = sanitized_msg
        record.error_details = str(exc)[:500]  # bounded internal diagnostic info
        record.retry_count = (record.retry_count or 0) + 1
        record.last_attempt_at = datetime.now(timezone.utc)
        db.commit()

        audit_service.log(
            db, "offline_patient.sync_failed",
            actor_user_id=current_user.id,
            entity_type="offline_registration",
            entity_id=record.id,
            after={"temp_ref_id": record.temp_ref_id, "reason": sanitized_msg, "retries": record.retry_count},
        )

        return {
            "status": "FAILED",
            "temp_ref_id": record.temp_ref_id,
            "failure_reason": sanitized_msg,
            "retry_count": record.retry_count,
        }


def retry_failed_registration(
    db: Session,
    record_id_or_ref: str,
    current_user: User,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Retries a selected failed cached registration.
    Enforces that only the creator/owner can retry it.
    Prevents concurrent duplicate retry attempts.
    """
    query = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.owner_id == current_user.id
    )

    # Try UUID match or temp_ref_id match
    try:
        rec_uuid = uuid.UUID(record_id_or_ref)
        record = query.filter(or_(CachedPatientRegistration.id == rec_uuid, CachedPatientRegistration.temp_ref_id == record_id_or_ref)).with_for_update().first()
    except ValueError:
        record = query.filter(CachedPatientRegistration.temp_ref_id == record_id_or_ref).with_for_update().first()

    if not record:
        raise HTTPException(status_code=404, detail="Failed cached record not found")

    if payload and payload.get("force_duplicate"):
        p_data = dict(record.patient_data or {})
        p_data["force_duplicate"] = True
        record.patient_data = p_data
        db.commit()

    if record.status == "SYNCING":
        # Check if stale (>60s)
        stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=60)
        if record.last_attempt_at and record.last_attempt_at < stale_threshold:
            # Stale lock recovery
            record.status = "FAILED"
            db.commit()
        else:
            raise HTTPException(status_code=409, detail="Retry is already in progress for this record.")

    if record.status == "SUCCESS":
        return {
            "status": "SUCCESS",
            "patient_id": str(record.permanent_patient_id) if record.permanent_patient_id else None,
            "patient_code": record.permanent_patient_code,
            "temp_ref_id": record.temp_ref_id,
            "message": "Patient is already synchronized.",
        }

    # Execute retry
    return process_single_registration(db, record, current_user)


def delete_failed_registration(
    db: Session,
    record_id_or_ref: str,
    current_user: User,
) -> Dict[str, Any]:
    """Discard a failed cached registration owned by the current user."""
    query = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.owner_id == current_user.id
    )
    try:
        rec_uuid = uuid.UUID(record_id_or_ref)
        record = query.filter(or_(CachedPatientRegistration.id == rec_uuid, CachedPatientRegistration.temp_ref_id == record_id_or_ref)).first()
    except ValueError:
        record = query.filter(CachedPatientRegistration.temp_ref_id == record_id_or_ref).first()

    if not record:
        raise HTTPException(status_code=404, detail="Failed cached record not found")

    db.delete(record)
    db.commit()
    return {"status": "DELETED", "temp_ref_id": record.temp_ref_id}


def list_failed_registrations(
    db: Session,
    current_user: User,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Returns FAILED records ONLY for the authenticated user.
    Admin sees only their own failed records.
    Staff sees only their own failed records.
    Pending, Syncing, and Success records are strictly excluded.
    """
    query = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.owner_id == current_user.id,
        CachedPatientRegistration.status == "FAILED"
    )

    if q and q.strip():
        search_term = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                CachedPatientRegistration.temp_ref_id.ilike(search_term),
                CachedPatientRegistration.patient_data["name"].astext.ilike(search_term),
                CachedPatientRegistration.patient_data["mobile"].astext.ilike(search_term),
            )
        )

    total = query.count()
    items = query.order_by(desc(CachedPatientRegistration.created_at)).offset((page - 1) * page_size).limit(page_size).all()

    formatted_items = []
    for item in items:
        p_data = item.patient_data or {}
        formatted_items.append({
            "id": str(item.id),
            "temp_ref_id": item.temp_ref_id,
            "patient_name": p_data.get("name", "Unknown Patient"),
            "mobile": p_data.get("mobile", ""),
            "age": p_data.get("age"),
            "gender": p_data.get("gender"),
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
            "failure_reason": item.failure_reason or "Unknown error",
            "retry_count": item.retry_count,
            "permanent_patient_id": str(item.permanent_patient_id) if item.permanent_patient_id else None,
            "permanent_patient_code": item.permanent_patient_code,
            "status": "FAILED",
            "patient_data": p_data,
        })

    return {
        "items": formatted_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_failed_registration(
    db: Session,
    record_id_or_ref: str,
    current_user: User,
) -> Dict[str, Any]:
    """Retrieve details for a single failed cached record owned by current_user."""
    query = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.owner_id == current_user.id,
        CachedPatientRegistration.status == "FAILED"
    )

    try:
        rec_uuid = uuid.UUID(record_id_or_ref)
        record = query.filter(or_(CachedPatientRegistration.id == rec_uuid, CachedPatientRegistration.temp_ref_id == record_id_or_ref)).first()
    except ValueError:
        record = query.filter(CachedPatientRegistration.temp_ref_id == record_id_or_ref).first()

    if not record:
        raise HTTPException(status_code=404, detail="Failed cached record not found")

    p_data = record.patient_data or {}
    return {
        "id": str(record.id),
        "temp_ref_id": record.temp_ref_id,
        "idempotency_key": record.idempotency_key,
        "patient_name": p_data.get("name", "Unknown Patient"),
        "mobile": p_data.get("mobile", ""),
        "age": p_data.get("age"),
        "gender": p_data.get("gender"),
        "doctor_id": str(p_data.get("doctor_id")) if p_data.get("doctor_id") else None,
        "sample_date": str(p_data.get("sample_date")) if p_data.get("sample_date") else None,
        "test_ids": p_data.get("test_ids", []),
        "total_amount": p_data.get("total_amount"),
        "discount_amount": p_data.get("discount_amount"),
        "amount_paid": p_data.get("amount_paid"),
        "payment_mode": p_data.get("payment_mode"),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "last_attempt_at": record.last_attempt_at.isoformat() if record.last_attempt_at else None,
        "failure_reason": record.failure_reason,
        "retry_count": record.retry_count,
        "permanent_patient_id": str(record.permanent_patient_id) if record.permanent_patient_id else None,
        "permanent_patient_code": record.permanent_patient_code,
        "status": "FAILED",
    }


def recover_stale_syncing_jobs(db: Session, max_age_seconds: int = 60, owner_user_id: Optional[uuid.UUID] = None) -> int:
    """
    Recovers jobs stuck in 'SYNCING' state due to worker or server crash.
    Transitions them back to 'FAILED' with a clear diagnostic so they can be retried safely.
    If owner_user_id is provided, only recovers records owned by that user.
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    query = db.query(CachedPatientRegistration).filter(
        CachedPatientRegistration.status == "SYNCING",
        CachedPatientRegistration.last_attempt_at < threshold
    )
    if owner_user_id:
        query = query.filter(CachedPatientRegistration.created_by_user_id == owner_user_id)

    stale_jobs = query.all()

    recovered_count = 0
    for job in stale_jobs:
        job.status = "FAILED"
        job.failure_reason = "Synchronization was interrupted by a connection drop or worker restart. Ready to retry."
        recovered_count += 1

    if recovered_count > 0:
        db.commit()
        logger.info(f"Recovered {recovered_count} stale SYNCING offline registration jobs.")

    return recovered_count
