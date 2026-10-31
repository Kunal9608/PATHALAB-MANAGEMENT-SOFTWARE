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
def recognize_and_checkin():
    """Biometric face recognition attendance is intentionally disabled in PathLab OS (SEC-02, SEC-04)."""
    from fastapi import HTTPException
    raise HTTPException(
        status_code=501,
        detail="Biometric face recognition attendance is intentionally disabled in PathLab OS."
    )


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
