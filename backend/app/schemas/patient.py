"""Patient schemas — comprehensive validation per SRS §5.4."""
import math
import re
import uuid
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator, model_validator


VALID_GENDERS = ("male", "female", "trans")
VALID_COLLECTIONS = ("self_center", "courier_serum", "courier_redcliffe")
VALID_PAYMENT_MODES = ("cash", "qr")
VALID_PATIENT_STATUSES = (
    "sample_collected",
    "sent_to_franchise",
    "under_process",
    "partial_release",
    "report_ready",
)


def _check_finite_amount(val: Optional[float], field_name: str) -> Optional[float]:
    """Validates that a financial amount is not NaN, Inf, or negative."""
    if val is None:
        return None
    if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
        raise ValueError(f"{field_name} must be a valid finite number")
    if val < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return float(val)


class PatientCreate(BaseModel):
    name: str
    age: int
    gender: str
    mobile: str
    doctor_id: Optional[uuid.UUID] = None
    test_ids: List[uuid.UUID]
    collection_type: str = "self_center"
    sample_date: Optional[date] = None
    estimated_report_date: Optional[date] = None
    amount_paid: float = 0.0
    discount_amount: float = 0.0
    payment_mode: Optional[str] = None
    force_duplicate: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not (2 <= len(v.strip()) <= 120):
            raise ValueError("Name must be 2–120 characters")
        return v.strip()

    @field_validator("age")
    @classmethod
    def validate_age(cls, v):
        if not (1 <= v <= 129):
            raise ValueError("Age must be between 1 and 129")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v not in VALID_GENDERS:
            raise ValueError(f"Gender must be one of {VALID_GENDERS}")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if not v or not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("test_ids")
    @classmethod
    def validate_tests(cls, v):
        if not v or len(v) == 0:
            raise ValueError("At least one test must be selected")
        return v

    @field_validator("collection_type")
    @classmethod
    def validate_collection_type(cls, v):
        if v not in VALID_COLLECTIONS:
            raise ValueError(f"collection_type must be one of {VALID_COLLECTIONS}")
        return v

    @field_validator("amount_paid")
    @classmethod
    def validate_amount_paid(cls, v):
        return _check_finite_amount(v, "amount_paid")

    @field_validator("discount_amount")
    @classmethod
    def validate_discount_amount(cls, v):
        return _check_finite_amount(v, "discount_amount")

    @model_validator(mode="after")
    def validate_payment_and_dates(self):
        if self.amount_paid > 0 and not self.payment_mode:
            raise ValueError("payment_mode is required when amount is paid")
        if self.amount_paid == 0:
            self.payment_mode = None
        if self.payment_mode and self.payment_mode not in VALID_PAYMENT_MODES:
            raise ValueError(f"payment_mode must be one of {VALID_PAYMENT_MODES}")
        sample = self.sample_date or date.today()
        if self.estimated_report_date and self.estimated_report_date < sample:
            raise ValueError("estimated_report_date must be >= sample_date")
        return self


class PatientUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    mobile: Optional[str] = None
    doctor_id: Optional[uuid.UUID] = None
    test_ids: Optional[List[uuid.UUID]] = None
    collection_type: Optional[str] = None
    sample_date: Optional[date] = None
    estimated_report_date: Optional[date] = None
    amount_paid: Optional[float] = None
    discount_amount: Optional[float] = None
    payment_mode: Optional[str] = None
    status: Optional[str] = None
    processing_note: Optional[str] = None
    force_duplicate: bool = False
    
    # Franchise Fields
    franchise_name: Optional[str] = None
    franchise_other: Optional[str] = None
    sample_sent_date: Optional[date] = None
    sample_sent_time: Optional[str] = None
    courier_name: Optional[str] = None
    tracking_id: Optional[str] = None
    franchise_remarks: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            if not (2 <= len(v.strip()) <= 120):
                raise ValueError("Name must be 2–120 characters")
            return v.strip()
        return v

    @field_validator("age")
    @classmethod
    def validate_age(cls, v):
        if v is not None and not (1 <= v <= 129):
            raise ValueError("Age must be between 1 and 129")
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v is not None and v not in VALID_GENDERS:
            raise ValueError(f"Gender must be one of {VALID_GENDERS}")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if v is not None and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("test_ids")
    @classmethod
    def validate_tests(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("test_ids cannot be empty if provided")
        return v

    @field_validator("collection_type")
    @classmethod
    def validate_collection_type(cls, v):
        if v is not None and v not in VALID_COLLECTIONS:
            raise ValueError(f"collection_type must be one of {VALID_COLLECTIONS}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in VALID_PATIENT_STATUSES:
            raise ValueError(f"status must be one of {VALID_PATIENT_STATUSES}")
        return v

    @field_validator("payment_mode")
    @classmethod
    def validate_payment_mode(cls, v):
        if v is not None and v not in VALID_PAYMENT_MODES:
            raise ValueError(f"payment_mode must be one of {VALID_PAYMENT_MODES}")
        return v

    @field_validator("amount_paid")
    @classmethod
    def validate_amount_paid(cls, v):
        return _check_finite_amount(v, "amount_paid")

    @field_validator("discount_amount")
    @classmethod
    def validate_discount_amount(cls, v):
        return _check_finite_amount(v, "discount_amount")

    @model_validator(mode="after")
    def validate_payment_and_dates(self):
        if self.amount_paid is not None and self.amount_paid > 0 and not self.payment_mode:
            raise ValueError("payment_mode is required when amount is paid")
        if self.sample_date and self.estimated_report_date:
            if self.estimated_report_date < self.sample_date:
                raise ValueError("estimated_report_date must be >= sample_date")
        return self


class TestSummary(BaseModel):
    id: uuid.UUID
    name: str
    price_at_booking: float

    class Config:
        from_attributes = True


class PatientResponse(BaseModel):
    id: uuid.UUID
    patient_code: str
    name: str
    age: int
    gender: str
    mobile: str
    doctor_id: Optional[uuid.UUID]
    doctor_name: Optional[str] = None
    collection_type: str
    sample_date: Optional[date]
    estimated_report_date: date
    total_amount: float
    discount_amount: float = 0.0
    amount_paid: float
    amount_due: float
    payment_mode: Optional[str]
    payment_status: str
    status: str
    processing_note: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    tests: List[TestSummary] = []
    collected_by_name: Optional[str] = None
    
    # Franchise Fields
    franchise_name: Optional[str] = None
    franchise_other: Optional[str] = None
    sample_sent_date: Optional[date] = None
    sample_sent_time: Optional[str] = None
    courier_name: Optional[str] = None
    tracking_id: Optional[str] = None
    franchise_remarks: Optional[str] = None
    status_history: Optional[List[dict]] = None

    class Config:
        from_attributes = True


class PatientListResponse(BaseModel):
    items: List[PatientResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
