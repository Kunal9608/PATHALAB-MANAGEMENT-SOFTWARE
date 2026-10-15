"""Test repository."""
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple
import uuid

from backend.app.models.test import Test
from backend.app.models.test_price_history import TestPriceHistory
from backend.app.models.doctor import Doctor


def get_all_tests(db: Session, active_only: bool = True) -> List[Test]:
    q = db.query(Test)
    if active_only:
        q = q.filter(Test.is_active == True)
    return q.order_by(Test.name).all()


def get_tests_paginated(
    db: Session,
    active_only: bool = True,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
) -> Tuple[List[Test], int]:
    """Paginated + searchable test list."""
    query = db.query(Test)
    if active_only:
        query = query.filter(Test.is_active == True)
    if q:
        query = query.filter(Test.name.ilike(f"%{q.strip()}%"))
    count_q = query.limit(1000).subquery()
    total = db.query(count_q).count()
    items = query.order_by(Test.name).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def get_test_by_id(db: Session, test_id: uuid.UUID) -> Optional[Test]:
    return db.query(Test).filter(Test.id == test_id).first()


def get_test_by_name(db: Session, name: str) -> Optional[Test]:
    return db.query(Test).filter(Test.name.ilike(name.strip())).first()


def generate_test_code(db: Session, year: int) -> str:
    from sqlalchemy import text
    seq_name = f"test_seq_{year}"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"))
    result = db.execute(text(f"SELECT nextval('{seq_name}')"))
    seq_val = result.scalar()
    year_short = str(year)[-2:]
    padded = str(seq_val).zfill(3)
    return f"TEST{year_short}{padded}"


def backfill_test_codes(db: Session):
    from datetime import datetime
    tests = db.query(Test).filter((Test.test_code.is_(None)) | (Test.test_code == "")).all()
    if not tests:
        return
    current_year = datetime.now().year
    for test in tests:
        test.test_code = generate_test_code(db, current_year)
    db.commit()


def create_test(db: Session, name: str, price: float, category: Optional[str] = None) -> Test:
    from datetime import datetime
    current_year = datetime.now().year
    code = generate_test_code(db, current_year)
    test = Test(name=name.strip(), price=price, category=category, test_code=code)
    db.add(test)
    db.flush()
    return test


def update_test(db: Session, test_id: uuid.UUID, **kwargs) -> Optional[Tuple[Test, float]]:
    test = get_test_by_id(db, test_id)
    if not test:
        return None
    old_price = float(test.price)
    for k, v in kwargs.items():
        setattr(test, k, v)
    db.flush()
    return test, old_price


def record_price_change(db: Session, test_id: uuid.UUID, old_price: float,
                        new_price: float, changed_by: uuid.UUID):
    history = TestPriceHistory(
        test_id=test_id, old_price=old_price,
        new_price=new_price, changed_by=changed_by
    )
    db.add(history)
    db.flush()


def get_current_prices(db: Session, test_ids: List[uuid.UUID]) -> dict:
    """Returns {test_id: price} for quick total computation."""
    tests = db.query(Test).filter(Test.id.in_(test_ids)).all()
    return {str(t.id): float(t.price) for t in tests}


# Doctor CRUD
def get_all_doctors(db: Session, include_inactive: bool = False) -> List[Doctor]:
    q = db.query(Doctor)
    if not include_inactive:
        q = q.filter(Doctor.is_active == True)
    return q.order_by(Doctor.name).all()


def get_doctors_paginated(
    db: Session,
    include_inactive: bool = False,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Doctor], int]:
    query = db.query(Doctor)
    if not include_inactive:
        query = query.filter(Doctor.is_active == True)
    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            Doctor.name.ilike(search) | Doctor.clinic_name.ilike(search)
        )
    total = query.count()
    items = query.order_by(Doctor.name).offset((page - 1) * page_size).limit(page_size).all()
    return items, total



def get_doctor_by_id(db: Session, doctor_id: uuid.UUID) -> Optional[Doctor]:
    return db.query(Doctor).filter(Doctor.id == doctor_id).first()


def create_doctor(db: Session, name: str, clinic_name: Optional[str] = None, commission_pct: float = 0.0) -> Doctor:
    doc = Doctor(name=name.strip(), clinic_name=clinic_name, commission_pct=commission_pct)
    db.add(doc)
    db.flush()
    return doc


def update_doctor(db: Session, doctor_id: uuid.UUID, **updates) -> Optional[Doctor]:
    doc = get_doctor_by_id(db, doctor_id)
    if not doc:
        return None
    for k, v in updates.items():
        if v is not None:
            setattr(doc, k, v)
    db.flush()
    return doc
