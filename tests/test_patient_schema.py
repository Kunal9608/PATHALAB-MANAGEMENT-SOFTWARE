"""
Comprehensive Unit & Regression Tests for Patient Schema Validation (CRIT-03 & HIGH-04)
"""
import uuid
import pytest
import math
from datetime import date, timedelta

from backend.app.schemas.patient import PatientCreate, PatientUpdate


VALID_TEST_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# PatientCreate Tests
# ---------------------------------------------------------------------------

def test_valid_patient_create():
    """Verify a well-formed PatientCreate payload passes validation."""
    payload = PatientCreate(
        name="Aarav Sharma",
        age=32,
        gender="male",
        mobile="9876543210",
        test_ids=[VALID_TEST_ID],
        amount_paid=500.0,
        payment_mode="cash"
    )
    assert payload.name == "Aarav Sharma"
    assert payload.age == 32
    assert payload.gender == "male"
    assert payload.amount_paid == 500.0
    assert payload.payment_mode == "cash"


@pytest.mark.parametrize("invalid_age", [-10, 0, 130, 250])
def test_patient_create_invalid_age(invalid_age):
    """Verify out-of-range age is rejected."""
    with pytest.raises(ValueError, match="Age must be between 1 and 129"):
        PatientCreate(
            name="Test Patient",
            age=invalid_age,
            gender="male",
            mobile="9876543210",
            test_ids=[VALID_TEST_ID]
        )


@pytest.mark.parametrize("invalid_gender", ["robot", "unknown", "other", "M", ""])
def test_patient_create_invalid_gender(invalid_gender):
    """Verify unsupported gender is rejected."""
    with pytest.raises(ValueError, match="Gender must be one of"):
        PatientCreate(
            name="Test Patient",
            age=25,
            gender=invalid_gender,
            mobile="9876543210",
            test_ids=[VALID_TEST_ID]
        )


@pytest.mark.parametrize("invalid_mobile", [
    "1234567890",   # Starts with 1 (not 6-9)
    "5987654321",   # Starts with 5
    "987654321",    # 9 digits
    "98765432100",  # 11 digits
    "98765abcde",   # Alphabetic
    ""              # Empty
])
def test_patient_create_invalid_mobile(invalid_mobile):
    """Verify malformed mobile number is rejected."""
    with pytest.raises(ValueError, match="Must be a valid 10-digit Indian mobile number"):
        PatientCreate(
            name="Test Patient",
            age=25,
            gender="female",
            mobile=invalid_mobile,
            test_ids=[VALID_TEST_ID]
        )


@pytest.mark.parametrize("invalid_val", [
    float("nan"),
    float("inf"),
    float("-inf"),
    -50.0
])
def test_patient_create_rejects_nan_and_inf_in_financials(invalid_val):
    """HIGH-04: Verify IEEE 754 NaN and Infinity are strictly rejected in amount_paid and discount_amount."""
    with pytest.raises(ValueError, match="must be a valid finite number|cannot be negative"):
        PatientCreate(
            name="Test Patient",
            age=25,
            gender="female",
            mobile="9876543210",
            test_ids=[VALID_TEST_ID],
            amount_paid=invalid_val,
            payment_mode="cash"
        )

    with pytest.raises(ValueError, match="must be a valid finite number|cannot be negative"):
        PatientCreate(
            name="Test Patient",
            age=25,
            gender="female",
            mobile="9876543210",
            test_ids=[VALID_TEST_ID],
            discount_amount=invalid_val
        )


# ---------------------------------------------------------------------------
# PatientUpdate Tests (CRIT-03)
# ---------------------------------------------------------------------------

def test_valid_patient_partial_update():
    """Verify partial updates with subset of valid fields pass."""
    payload = PatientUpdate(name="Pooja Verma", age=29)
    assert payload.name == "Pooja Verma"
    assert payload.age == 29
    assert payload.gender is None
    assert payload.mobile is None


@pytest.mark.parametrize("invalid_age", [-7, 0, 130, 999])
def test_patient_update_invalid_age(invalid_age):
    """CRIT-03: Verify negative or out-of-range age in PatientUpdate is rejected."""
    with pytest.raises(ValueError, match="Age must be between 1 and 129"):
        PatientUpdate(age=invalid_age)


@pytest.mark.parametrize("invalid_gender", ["robot", "unknown", "alien"])
def test_patient_update_invalid_gender(invalid_gender):
    """CRIT-03: Verify invalid gender in PatientUpdate is rejected."""
    with pytest.raises(ValueError, match="Gender must be one of"):
        PatientUpdate(gender=invalid_gender)


@pytest.mark.parametrize("invalid_mobile", ["123", "0000000000", "5987654321", "abcdefghij"])
def test_patient_update_invalid_mobile(invalid_mobile):
    """CRIT-03: Verify invalid mobile in PatientUpdate is rejected."""
    with pytest.raises(ValueError, match="Must be a valid 10-digit Indian mobile number"):
        PatientUpdate(mobile=invalid_mobile)


@pytest.mark.parametrize("invalid_val", [
    float("nan"),
    float("inf"),
    float("-inf"),
    -100.0
])
def test_patient_update_rejects_nan_and_inf_in_financials(invalid_val):
    """HIGH-04 / CRIT-03: Verify NaN and Inf in PatientUpdate financial fields are rejected."""
    with pytest.raises(ValueError, match="must be a valid finite number|cannot be negative"):
        PatientUpdate(amount_paid=invalid_val)

    with pytest.raises(ValueError, match="must be a valid finite number|cannot be negative"):
        PatientUpdate(discount_amount=invalid_val)


def test_patient_update_invalid_status():
    """CRIT-03: Verify unsupported status in PatientUpdate is rejected."""
    with pytest.raises(ValueError, match="status must be one of"):
        PatientUpdate(status="random_bad_status")


def test_patient_update_invalid_payment_mode():
    """CRIT-03: Verify unsupported payment mode in PatientUpdate is rejected."""
    with pytest.raises(ValueError, match="payment_mode must be one of"):
        PatientUpdate(payment_mode="bitcoin")


def test_patient_update_estimated_date_before_sample_date():
    """Verify estimated_report_date cannot be earlier than sample_date."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    with pytest.raises(ValueError, match="estimated_report_date must be >= sample_date"):
        PatientUpdate(sample_date=today, estimated_report_date=yesterday)

