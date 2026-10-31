"""Staff schemas."""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import date, datetime
import re
import uuid


class StaffCreate(BaseModel):
    name: str
    email: EmailStr
    mobile: str
    dob: Optional[date] = None
    aadhar: Optional[str] = None  # 12 digits, validated
    view_scope: str = "own"

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("aadhar")
    @classmethod
    def validate_aadhar(cls, v):
        if v:
            cleaned = re.sub(r"[\s\-]", "", str(v).strip())
            if not re.match(r"^\d{12}$", cleaned):
                raise ValueError("Aadhar must be exactly 12 digits")
            return cleaned
        return v

    @field_validator("view_scope")
    @classmethod
    def validate_scope(cls, v):
        if v not in ("all", "own"):
            raise ValueError("view_scope must be 'all' or 'own'")
        return v


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    dob: Optional[date] = None
    aadhar: Optional[str] = None
    view_scope: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v):
        if v and not re.match(r"^[6-9]\d{9}$", v):
            raise ValueError("Must be a valid 10-digit Indian mobile number")
        return v

    @field_validator("aadhar")
    @classmethod
    def validate_aadhar(cls, v):
        if v:
            cleaned = re.sub(r"[\s\-]", "", str(v).strip())
            if not re.match(r"^\d{12}$", cleaned):
                raise ValueError("Aadhar must be exactly 12 digits")
            return cleaned
        return v


class StaffResponse(BaseModel):
    id: uuid.UUID
    staff_code: Optional[str] = None
    name: str
    email: str
    mobile: Optional[str]
    role: str
    view_scope: str
    face_registered: bool
    is_active: bool
    created_at: datetime
    aadhar_last4: Optional[str] = None

    class Config:
        from_attributes = True


class FaceEnrollResponse(BaseModel):
    accepted: bool
    reason: Optional[str] = None
    sample_count: int = 0
    face_registered: bool = False
    is_active: bool = False
    message: str = ""
