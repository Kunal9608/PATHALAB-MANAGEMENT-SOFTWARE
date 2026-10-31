"""Test catalog router."""
from fastapi import APIRouter, Depends, Query, Body, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Any, List, Dict
import uuid

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin
from backend.app.schemas.test import TestCreate, TestUpdate, DoctorCreate, DoctorUpdate
from backend.app.services import test_service
from backend.app.repositories import test_repo

router = APIRouter(tags=["tests"])


# --- Tests ---
test_router = APIRouter(prefix="/tests")

@test_router.get("")
def list_tests(
    active_only: bool = True,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Paginated + searchable test catalog."""
    return test_service.get_tests_paginated(db, active_only, q, page, page_size)


@test_router.get("/{test_id}/price-history")
def get_price_history(
    test_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return price change history for a test."""
    from backend.app.models.test_price_history import TestPriceHistory
    from backend.app.models.user import User
    from sqlalchemy.orm import joinedload
    rows = (
        db.query(TestPriceHistory)
        .options(joinedload(TestPriceHistory.changed_by_user))
        .filter(TestPriceHistory.test_id == test_id)
        .order_by(TestPriceHistory.changed_at.desc())
        .all()
    )
    return [
        {
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            "old_price": float(r.old_price),
            "new_price": float(r.new_price),
            "changed_by_name": r.changed_by_user.name if r.changed_by_user else None,
        }
        for r in rows
    ]


@test_router.get("/{test_id}")
def get_test(
    test_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    t = test_repo.get_test_by_id(db, test_id)
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Test not found")
    return test_service._test_to_dict(t)


@test_router.post("", status_code=201)
def create_test(
    payload: TestCreate,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    category = payload.category or getattr(payload, 'description', None)
    return test_service.create_test(db, payload.name, payload.price, category, admin.id)


@test_router.patch("/{test_id}")
def update_test(
    test_id: uuid.UUID,
    payload: TestUpdate,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.category is None and payload.description is not None:
        payload.category = payload.description
    return test_service.update_test(db, test_id, payload, admin.id)


@test_router.delete("/{test_id}")
def soft_delete_test(
    test_id: uuid.UUID,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft-delete — sets is_active=False."""
    from backend.app.schemas.test import TestUpdate
    payload = TestUpdate(is_active=False)
    return test_service.update_test(db, test_id, payload, admin.id)


@test_router.get("/{test_id}/parameters")
def get_test_parameters(
    test_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from backend.app.services import test_parameter_service
    from backend.app.schemas.test_parameter import TestParameterResponse
    params = test_parameter_service.get_test_parameters(db, test_id)
    return [TestParameterResponse.model_validate(p) for p in params]


@test_router.post("/{test_id}/parameters")
def save_test_parameters(
    test_id: uuid.UUID,
    payload: Any = Body(...),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    from backend.app.schemas.test_parameter import TestParameterBulkSave, TestParameterResponse
    from backend.app.services import test_parameter_service
    if isinstance(payload, dict):
        bulk_save = TestParameterBulkSave.model_validate(payload)
    else:
        bulk_save = payload
    params = test_parameter_service.save_test_parameters(db, test_id, bulk_save, admin.id)
    return [TestParameterResponse.model_validate(p) for p in params]


@test_router.post("/seed-parameters")
@test_router.post("/seed-standard-catalog")
def seed_parameters_endpoint(
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin endpoint to trigger pre-population of test parameters for standard tests."""
    from backend.seed.seed_parameters import seed_test_parameters
    count = seed_test_parameters(db)
    return {"status": "ok", "seeded_tests_count": count, "seeded_count": count}


# --- Doctors ---
doctor_router = APIRouter(prefix="/doctors")

@doctor_router.get("")
def list_doctors(
    include_inactive: bool = Query(False),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return test_service.get_doctors_paginated(db, include_inactive, q, page, page_size)


@doctor_router.post("", status_code=201)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db),
                  admin=Depends(require_admin)):
    return test_service.create_doctor(db, payload.name, payload.clinic_name, payload.commission_pct, admin.id)


@doctor_router.patch("/{doctor_id}")
def update_doctor(doctor_id: uuid.UUID, payload: DoctorUpdate, db: Session = Depends(get_db),
                  admin=Depends(require_admin)):
    try:
        return test_service.update_doctor(db, doctor_id, payload, admin.id)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))


router.include_router(test_router)
router.include_router(doctor_router)
