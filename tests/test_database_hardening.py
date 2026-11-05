"""
Automated unit and integration regression test suite for Enterprise PostgreSQL Database Hardening.
Verifies DB-04 (Check constraints), DB-05 (Indexes), DB-06 (RLS uniformity).
"""
import pytest
import uuid
from decimal import Decimal
from datetime import date
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from backend.app.core.db import SessionLocal
from backend.app.models.patient import Patient, GenderEnum, CollectionTypeEnum
from backend.app.models.expense import Expense, ExpenseCategoryEnum, ExpensePaymentModeEnum
from backend.app.models.user import User


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_db_check_constraint_rejects_negative_patient_total(db_session):
    """Verify PostgreSQL check constraint rejects total_amount < 0."""
    admin_user = db_session.query(User).first()
    assert admin_user is not None, "Admin user must exist in DB for test"

    invalid_patient = Patient(
        patient_code=f"TEST_NEG_{uuid.uuid4().hex[:6]}",
        name="Negative Amount Patient",
        age=30,
        gender=GenderEnum.male,
        mobile="9876543210",
        collected_by=admin_user.id,
        collection_type=CollectionTypeEnum.self_center,
        estimated_report_date=date.today(),
        total_amount=Decimal("-150.00"),
        discount_amount=None,  # Leave None so chk_patients_discount_le_total passes and chk_patients_positive_amounts fires
        amount_paid=Decimal("0.00"),
    )
    db_session.add(invalid_patient)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    err = str(exc_info.value).lower()
    assert "chk_patients_positive_amounts" in err or "chk_patients_discount_le_total" in err
    db_session.rollback()


def test_db_check_constraint_rejects_discount_greater_than_total(db_session):
    """Verify PostgreSQL check constraint rejects discount_amount > total_amount."""
    admin_user = db_session.query(User).first()
    assert admin_user is not None

    invalid_patient = Patient(
        patient_code=f"TEST_DISC_{uuid.uuid4().hex[:6]}",
        name="Excess Discount Patient",
        age=45,
        gender=GenderEnum.female,
        mobile="9876543210",
        collected_by=admin_user.id,
        collection_type=CollectionTypeEnum.self_center,
        estimated_report_date=date.today(),
        total_amount=Decimal("500.00"),
        discount_amount=Decimal("600.00"),  # Violates chk_patients_discount_le_total
        amount_paid=Decimal("0.00"),
    )
    db_session.add(invalid_patient)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "chk_patients_discount_le_total" in str(exc_info.value).lower()
    db_session.rollback()


def test_db_check_constraint_rejects_negative_expense_amount(db_session):
    """Verify PostgreSQL check constraint rejects expense amount <= 0."""
    admin_user = db_session.query(User).first()
    assert admin_user is not None

    invalid_expense = Expense(
        category=ExpenseCategoryEnum.utilities,
        amount=Decimal("-500.00"),  # Violates chk_expenses_positive_amount
        payment_mode=ExpensePaymentModeEnum.cash,
        recorded_by=admin_user.id,
    )
    db_session.add(invalid_expense)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "chk_expenses_positive_amount" in str(exc_info.value).lower()
    db_session.rollback()


def test_db_indexes_and_rls_exist_in_postgresql(db_session):
    """Verify that all new composite and partial indexes and RLS are registered in PostgreSQL system catalogs."""
    # 1. RLS
    rls_val = db_session.execute(sa.text("""
        SELECT relrowsecurity 
        FROM pg_class 
        WHERE relname = 'copilot_messages' AND relnamespace = 'public'::regnamespace;
    """)).scalar()
    assert rls_val is True, "copilot_messages must have relrowsecurity == True"

    # 2. Indexes
    expected_indexes = {
        "idx_active_sessions_unrevoked",
        "idx_patients_status_created",
        "idx_reports_patient_uploaded",
        "idx_expenses_category_date",
        "idx_copilot_messages_user_created"
    }
    existing_indexes = set(db_session.execute(sa.text("""
        SELECT indexname 
        FROM pg_indexes 
        WHERE schemaname = 'public';
    """)).scalars().all())

    for idx in expected_indexes:
        assert idx in existing_indexes, f"Index '{idx}' must exist in PostgreSQL"
