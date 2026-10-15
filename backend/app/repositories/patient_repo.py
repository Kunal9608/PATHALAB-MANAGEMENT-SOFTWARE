"""Patient repository — all DB queries for patients, patient_tests."""
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, or_, and_, desc
from typing import Optional, List, Tuple
from datetime import date, datetime, timezone
import uuid

from backend.app.models.patient import Patient, PatientStatusEnum
from backend.app.models.patient_test import PatientTest
from backend.app.models.test import Test
from backend.app.models.doctor import Doctor
from backend.app.models.patient_status_history import PatientStatusHistory


def create_patient(db: Session, **kwargs) -> Patient:
    patient = Patient(**kwargs)
    db.add(patient)
    db.flush()
    return patient


def add_patient_test(db: Session, patient_id: uuid.UUID, test_id: uuid.UUID, price: float) -> PatientTest:
    pt = PatientTest(patient_id=patient_id, test_id=test_id, price_at_booking=price)
    db.add(pt)
    db.flush()
    return pt

def get_by_id(db: Session, patient_id: uuid.UUID) -> Optional[Patient]:
    return (
        db.query(Patient)
        .options(
            selectinload(Patient.patient_tests).joinedload(PatientTest.test),
            joinedload(Patient.doctor),
            joinedload(Patient.collector),
            selectinload(Patient.reports),
            selectinload(Patient.status_history).joinedload(PatientStatusHistory.updater),
        )
        .filter(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .first()
    )


def get_by_code(db: Session, patient_code: str) -> Optional[Patient]:
    return db.query(Patient).filter(Patient.patient_code == patient_code).first()


def list_patients(
    db: Session,
    q: Optional[str] = None,
    doctor_id: Optional[uuid.UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    collected_by: Optional[uuid.UUID] = None,  # for view_scope enforcement
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Patient], int]:
    query = (
        db.query(Patient)
        .options(
            selectinload(Patient.patient_tests).joinedload(PatientTest.test),
            joinedload(Patient.doctor),
            joinedload(Patient.collector),
            selectinload(Patient.reports),
        )
        .filter(Patient.deleted_at.is_(None))
    )

    # 2. Base query for count (NO joinedload to prevent expensive joins)
    count_query = db.query(Patient).filter(Patient.deleted_at.is_(None))

    if q:
        # Use prefix search if exact code/phone/name or wildcard
        search = f"{q}%" if not q.startswith("%") else q
        flt = or_(
            Patient.name.ilike(search),
            Patient.mobile.ilike(search),
            Patient.patient_code.ilike(search),
        )
        query = query.filter(flt)
        count_query = count_query.filter(flt)

    if doctor_id:
        query = query.filter(Patient.doctor_id == doctor_id)
        count_query = count_query.filter(Patient.doctor_id == doctor_id)

    if date_from:
        start_dt = datetime.combine(date_from, datetime.min.time())
        query = query.filter(Patient.created_at >= start_dt)
        count_query = count_query.filter(Patient.created_at >= start_dt)

    if date_to:
        end_dt = datetime.combine(date_to, datetime.max.time())
        query = query.filter(Patient.created_at <= end_dt)
        count_query = count_query.filter(Patient.created_at <= end_dt)

    if status:
        query = query.filter(Patient.status == status)
        count_query = count_query.filter(Patient.status == status)

    if collected_by:  # view_scope = own enforcement — server-side
        query = query.filter(Patient.collected_by == collected_by)
        count_query = count_query.filter(Patient.collected_by == collected_by)

    # Accurate count for pagination
    # (Removed reltuples estimation as it causes missing pagination on tables < 100k rows)
    total = count_query.count()
    items = (
        query.order_by(desc(Patient.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def search_by_mobile(db: Session, mobile: str, collected_by: Optional[uuid.UUID] = None) -> List[Patient]:
    query = (
        db.query(Patient)
        .options(
            selectinload(Patient.patient_tests).joinedload(PatientTest.test),
            joinedload(Patient.doctor),
            joinedload(Patient.collector),
            selectinload(Patient.reports),
        )
        .filter(Patient.mobile == mobile, Patient.deleted_at.is_(None))
    )
    if collected_by:
        query = query.filter(Patient.collected_by == collected_by)
    return (
        query
        .order_by(desc(Patient.created_at))
        .limit(5)
        .all()
    )


def update_patient(db: Session, patient_id: uuid.UUID, **kwargs) -> Optional[Patient]:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return None
    for k, v in kwargs.items():
        setattr(patient, k, v)
    # pyrefly: ignore [bad-assignment]
    patient.updated_at = datetime.now(timezone.utc)
    db.flush()
    return patient


def delete_patient_tests(db: Session, patient_id: uuid.UUID):
    db.query(PatientTest).filter(PatientTest.patient_id == patient_id).delete()
    db.flush()


def get_today_stats(db: Session):
    today = date.today()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Count & sum computed inside SQL in one fast query matching sample_date or created_at UTC
    stats = db.query(
        func.count(Patient.id),
        func.sum(Patient.amount_paid)
    ).filter(
        or_(
            Patient.sample_date == today,
            and_(Patient.created_at >= start_of_day, Patient.created_at <= end_of_day)
        ),
        Patient.deleted_at.is_(None)
    ).first()

    # pyrefly: ignore [unsupported-operation]
    count = stats[0] or 0
    # pyrefly: ignore [unsupported-operation]
    revenue = float(stats[1] or 0)

    pending = db.query(Patient).filter(
        Patient.status.in_([PatientStatusEnum.sample_collected, PatientStatusEnum.under_process]),
        Patient.deleted_at.is_(None)
    ).count()

    due = db.query(func.sum(Patient.total_amount - Patient.discount_amount - Patient.amount_paid)).filter(
        Patient.deleted_at.is_(None),
        Patient.amount_paid < (Patient.total_amount - Patient.discount_amount)
    ).scalar() or 0

    return {"revenue": revenue, "count": count, "pending": pending, "due": float(due)}


def generate_patient_code(db: Session, year: int) -> str:
    """Generate Patient ID using PostgreSQL sequence — never MAX+1."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError, OperationalError
    seq_name = f"patient_seq_{year}"
    
    try:
        # Fast path: try to get nextval directly (works 99.9% of the time)
        result = db.execute(text(f"SELECT nextval('{seq_name}')"))
        seq_val = result.scalar()
    except (ProgrammingError, OperationalError):
        db.rollback()
        # Slow path: create sequence if it doesn't exist (first run or new year)
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"))
        result = db.execute(text(f"SELECT nextval('{seq_name}')"))
        seq_val = result.scalar()
        
    year_short = str(year)[-2:]
    padded = str(seq_val).zfill(4)
    return f"PAT{year_short}{padded}"
