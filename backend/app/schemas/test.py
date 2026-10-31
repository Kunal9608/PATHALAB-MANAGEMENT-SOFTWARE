"""Test catalog schemas."""
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
import uuid


class TestCreate(BaseModel):
    name: str
    price: float
    category: Optional[str] = None
    description: Optional[str] = None  # alias for category used by frontend

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Price must be non-negative")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Test name cannot be empty")
        return v.strip()


class TestUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None  # alias for category used by frontend
    is_active: Optional[bool] = None


class TestResponse(BaseModel):
    id: uuid.UUID
    test_code: Optional[str] = None
    name: str
    price: float
    category: Optional[str]
    parameters_count: Optional[int] = 0
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DoctorCreate(BaseModel):
    name: str
    clinic_name: Optional[str] = None
    commission_pct: float = 0.0


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    clinic_name: Optional[str] = None
    commission_pct: Optional[float] = None
    is_active: Optional[bool] = None


class DoctorResponse(BaseModel):
    id: uuid.UUID
    name: str
    clinic_name: Optional[str]
    commission_pct: float
    is_active: bool

    class Config:
        from_attributes = True
