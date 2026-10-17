"""Patient schemas — comprehensive validation per SRS §5.4."""
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List
from datetime import date, datetime
import re
import uuid


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
        if not (2 <= len(v.strip()) <= 120):
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
        if v not in ("male", "female", "trans"):
            raise ValueError("Gender must be male, female, or trans")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("test_ids")
    @classmethod
    def validate_tests(cls, v):
        if len(v) == 0:
            raise ValueError("At least one test must be selected")
        return v

    @field_validator("collection_type")
    @classmethod
    def validate_collection_type(cls, v):
        valid = ("self_center", "courier_serum", "courier_redcliffe")
        if v not in valid:
            raise ValueError(f"collection_type must be one of {valid}")
        return v

    @model_validator(mode="after")
    def validate_payment_mode(self):
        if self.amount_paid < 0:
            raise ValueError("amount_paid cannot be negative")
        if self.discount_amount < 0:
            raise ValueError("discount_amount cannot be negative")
        if self.amount_paid > 0 and not self.payment_mode:
            raise ValueError("payment_mode is required when amount is paid")
        if self.amount_paid == 0:
            self.payment_mode = None
        if self.payment_mode and self.payment_mode not in ("cash", "qr"):
            raise ValueError("payment_mode must be cash or qr")
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
