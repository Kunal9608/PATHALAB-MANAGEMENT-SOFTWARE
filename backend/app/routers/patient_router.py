"""Patient router."""
from fastapi import APIRouter, Depends, Query, Header, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
import uuid

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, get_idempotency_key, check_patient_access
from backend.app.schemas.patient import PatientCreate, PatientUpdate
from backend.app.services import patient_service, idempotency_service

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", status_code=201)
def create_patient(
    payload: PatientCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    if idempotency_key:
        return idempotency_service.with_idempotency(
            idempotency_key,
            str(current_user.id),
            lambda: patient_service.create_patient(db, payload, current_user.id, background_tasks)
        )

    return patient_service.create_patient(db, payload, current_user.id, background_tasks)


@router.get("")
def list_patients(
    q: Optional[str] = None,
    doctor_id: Optional[uuid.UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return patient_service.list_patients(
        db, current_user,
        q=q, doctor_id=doctor_id, date_from=date_from, date_to=date_to,
        status=status, page=page, page_size=page_size,
    )


from pydantic import BaseModel

class PatientSearchRequest(BaseModel):
    q: Optional[str] = None
    doctor_id: Optional[uuid.UUID] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    status: Optional[str] = None

@router.post("/search")
def search_patients(
    payload: PatientSearchRequest,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return patient_service.list_patients(
        db, current_user,
        q=payload.q, doctor_id=payload.doctor_id, date_from=payload.date_from, date_to=payload.date_to,
        status=payload.status, page=page, page_size=page_size,
    )


@router.get("/export")
def export_patients(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from backend.app.models.user import RoleEnum
    if current_user.role != RoleEnum.admin:
        raise HTTPException(status_code=403, detail="Only admins can export patients")
        
    parsed_date_from = None
    parsed_date_to = None
    
    if date_from:
        try:
            parsed_date_from = date.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")
    if date_to:
        try:
            parsed_date_to = date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")
            
    if parsed_date_from or parsed_date_to:
        if not (parsed_date_from and parsed_date_to):
            raise HTTPException(status_code=400, detail="Both date_from and date_to must be provided")
        if (parsed_date_to - parsed_date_from).days > 15:
            raise HTTPException(status_code=400, detail="Maximum 15 days of data can be exported at a time")
        if (parsed_date_to - parsed_date_from).days < 0:
            raise HTTPException(status_code=400, detail="date_to must be after date_from")

    return patient_service.export_patients_csv(db, parsed_date_from, parsed_date_to)


@router.get("/search")
def search_by_mobile(
    mobile: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from backend.app.repositories import patient_repo
    from backend.app.models.user import RoleEnum, ViewScopeEnum
    collected_by = None
    if current_user.role == RoleEnum.staff and current_user.view_scope == ViewScopeEnum.own:
        collected_by = current_user.id
    patients = patient_repo.search_by_mobile(db, mobile, collected_by=collected_by)
    return [patient_service._patient_to_dict(db, p) for p in patients]


@router.get("/{patient_id}")
def get_patient(patient_id: uuid.UUID, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)
    return patient_service.get_patient(db, patient_id)


@router.patch("/{patient_id}")
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)
    return patient_service.update_patient(db, patient_id, payload, current_user.id, background_tasks)


@router.post("/{patient_id}/qr-code")
def get_qr_code(patient_id: uuid.UUID, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)
    upi_string = patient_service.generate_qr_payload(db, patient_id)
    return {"upi_string": upi_string}
