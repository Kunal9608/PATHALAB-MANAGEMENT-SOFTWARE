"""Attendance router."""
from fastapi import APIRouter, Depends, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
import uuid

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin, get_client_ip, get_idempotency_key
from backend.app.services import attendance_service
from backend.app.core.limiter import limiter

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/recognize")
@limiter.limit("10/minute")
async def recognize_and_checkin(
    request: Request,
    image: UploadFile = File(...),
    device_id: Optional[str] = None,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """FR-3.1 — Submit camera frame for face recognition + auto check-in/out."""
    from fastapi import HTTPException
    
    from backend.app.core.upload_security import read_upload_file_bounded, validate_file_upload
    allowed_image_exts = (".jpg", ".jpeg", ".png", ".webp")
    max_kiosk_size = 10 * 1024 * 1024  # 10MB

    # Stream read with strict maximum limit to prevent memory exhaustion
    try:
        image_bytes = await read_upload_file_bounded(image, max_size=max_kiosk_size)
        validate_file_upload(
            file_bytes=image_bytes,
            filename=image.filename,
            max_size=max_kiosk_size,
            allowed_extensions=allowed_image_exts
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    from backend.app.services import idempotency_service
    if idempotency_key:
        cached = idempotency_service.check_key_exists(idempotency_key, "kiosk")
        if cached:
            return cached
    result = attendance_service.recognize_and_log(db, image_bytes, device_id)

    if idempotency_key and result.get("matched"):
        idempotency_service.store_result(idempotency_key, "kiosk", result)

    return result


@router.post("/manual-checkin/{user_id}")
def manual_checkin(user_id: uuid.UUID, admin=Depends(require_admin),
                   db: Session = Depends(get_db)):
    """Admin manual attendance override."""
    return attendance_service.log_attendance(db, user_id, confidence=1.0, source="online")


@router.get("/report")
def attendance_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    user_id: Optional[uuid.UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=500),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return attendance_service.get_attendance_report(
        db, date_from, date_to, user_id, page=page, page_size=page_size
    )


@router.get("/today")
def today_attendance(admin=Depends(require_admin), db: Session = Depends(get_db)):
    today = date.today()
    return attendance_service.get_attendance_report(db, today, today)
