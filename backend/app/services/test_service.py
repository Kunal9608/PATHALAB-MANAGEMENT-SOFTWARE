"""Test service — catalog CRUD, price history."""
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session

from backend.app.repositories import test_repo
from backend.app.services import audit_service


def get_all_tests(db: Session, active_only: bool = True) -> List[dict]:
    tests = test_repo.get_all_tests(db, active_only)
    return [_test_to_dict(t) for t in tests]


def get_tests_paginated(
    db: Session,
    active_only: bool = True,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    items, total = test_repo.get_tests_paginated(db, active_only, q, page, page_size)
    total_pages = (total + page_size - 1) // page_size
    return {
        "items": [_test_to_dict(t) for t in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def create_test(db: Session, name: str, price: float,
                category: Optional[str], actor_id: uuid.UUID) -> dict:
    existing = test_repo.get_test_by_name(db, name)
    if existing:
        raise ValueError(f"Test '{name}' already exists")

    test = test_repo.create_test(db, name, price, category)
    audit_service.log(db, "test.create", actor_user_id=actor_id,
                      entity_type="test", entity_id=test.id,
                      after={"name": name, "price": price})
    db.commit()
    try:
        from backend.app.core import copilot_cache
        copilot_cache.invalidate_test_sync(str(test.test_code) if test and getattr(test, 'test_code', None) else None)
    except Exception:
        pass
    return _test_to_dict(test)


def update_test(db: Session, test_id: uuid.UUID, payload, actor_id: uuid.UUID) -> dict:
    result = test_repo.update_test(db, test_id, **payload.model_dump(exclude_none=True))
    if not result:
        raise ValueError("Test not found")

    test, old_price = result
    # Log price change if price changed
    new_price = payload.price
    if new_price is not None and float(old_price) != float(new_price):
        test_repo.record_price_change(db, test_id, old_price, new_price, actor_id)
        audit_service.log(db, "test.price_change", actor_user_id=actor_id,
                          entity_type="test", entity_id=test_id,
                          before={"price": old_price}, after={"price": new_price})

    db.commit()
    try:
        from backend.app.core import copilot_cache
        copilot_cache.invalidate_test_sync(str(test.test_code) if test and getattr(test, 'test_code', None) else None)
    except Exception:
        pass
    return _test_to_dict(test)


def get_all_doctors(db: Session, include_inactive: bool = False) -> List[dict]:
    doctors = test_repo.get_all_doctors(db, include_inactive)
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "clinic_name": d.clinic_name,
            "commission_pct": float(d.commission_pct),
            "is_active": d.is_active,
        }
        for d in doctors
    ]


def get_doctors_paginated(
    db: Session,
    include_inactive: bool = False,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if q:
        page_size = 3
    items, total = test_repo.get_doctors_paginated(db, include_inactive, q, page, page_size)
    total_pages = (total + page_size - 1) // page_size
    return {
        "items": [
            {
                "id": str(d.id),
                "name": d.name,
                "clinic_name": d.clinic_name,
                "commission_pct": float(d.commission_pct),
                "is_active": d.is_active,
            }
            for d in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }



def create_doctor(db: Session, name: str, clinic_name: Optional[str],
                  commission_pct: float, actor_id: uuid.UUID) -> dict:
    doc = test_repo.create_doctor(db, name, clinic_name, commission_pct)
    audit_service.log(db, "doctor.create", actor_user_id=actor_id,
                      entity_type="doctor", entity_id=doc.id,
                      after={"name": doc.name, "commission_pct": commission_pct})
    db.commit()
    return {
        "id": str(doc.id),
        "name": doc.name,
        "clinic_name": doc.clinic_name,
        "commission_pct": float(doc.commission_pct),
        "is_active": doc.is_active,
    }


def update_doctor(db: Session, doctor_id: uuid.UUID, payload, actor_id: uuid.UUID) -> dict:
    doc = test_repo.get_doctor_by_id(db, doctor_id)
    if not doc:
        raise ValueError("Doctor not found")
    before = {
        "name": doc.name,
        "clinic_name": doc.clinic_name,
        "commission_pct": float(doc.commission_pct),
        "is_active": doc.is_active,
    }
    updates = payload.model_dump(exclude_none=True)
    updated = test_repo.update_doctor(db, doctor_id, **updates)
    if not updated:
        raise ValueError("Doctor not found")
    audit_service.log(db, "doctor.edit", actor_user_id=actor_id,
                      entity_type="doctor", entity_id=doctor_id,
                      before=before, after=updates)
    db.commit()
    return {
        "id": str(updated.id),
        "name": updated.name,
        "clinic_name": updated.clinic_name,
        "commission_pct": float(updated.commission_pct),
        "is_active": updated.is_active,
    }


def _test_to_dict(test) -> dict:
    return {
        "id": str(test.id),
        "test_code": test.test_code,
        "name": test.name,
        "description": test.category or "",  # category shown as 'Description' column in UI
        "price": float(test.price),
        "category": test.category,
        "is_active": test.is_active,
        "created_at": test.created_at.isoformat() if test.created_at else None,
    }
