"""Patient model — full schema per SRS §4.2."""
import uuid
from datetime import datetime, date, timezone
from sqlalchemy import (
    Column, String, SmallInteger, Enum, Numeric, Date,
    DateTime, ForeignKey, CheckConstraint, text, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from backend.app.core.db import Base


class GenderEnum(str, enum.Enum):
    male = "male"
    female = "female"
    trans = "trans"


class CollectionTypeEnum(str, enum.Enum):
    self_center = "self_center"
    courier_serum = "courier_serum"
    courier_redcliffe = "courier_redcliffe"


class PatientStatusEnum(str, enum.Enum):
    sample_collected = "sample_collected"
    sent_to_franchise = "sent_to_franchise"
    under_process = "under_process"
    partial_release = "partial_release"
    report_ready = "report_ready"


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                server_default=text("gen_random_uuid()"))
    patient_code = Column(String(16), nullable=False, unique=True)
    name = Column(String(120), nullable=False, index=True)
    age = Column(SmallInteger, nullable=False)
    gender = Column(Enum(GenderEnum, name="gender_enum"), nullable=False)
    mobile = Column(String(10), nullable=False, index=True)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=True, index=True)
    collected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    collection_type = Column(Enum(CollectionTypeEnum, name="collection_type_enum"), nullable=False,
                             default="self_center")
    sample_date = Column(Date, default=lambda: date.today())
    estimated_report_date = Column(Date, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), default=0, nullable=True)
    amount_paid = Column(Numeric(10, 2), default=0)
    referred_doctor_commission_pct = Column(Numeric(5, 2), default=0.0, nullable=True)
    referred_doctor_commission_amount = Column(Numeric(10, 2), default=0.0, nullable=True)
    # amount_due is computed in Python (PG GENERATED ALWAYS AS not easily mapped in SQLAlchemy)
    payment_mode = Column(Enum("cash", "qr", name="payment_mode_enum"), nullable=True)
    status = Column(Enum(PatientStatusEnum, name="patient_status_enum"), default="sample_collected")
    
    # Franchise Fields
    franchise_name = Column(String(100), nullable=True)
    franchise_other = Column(String(100), nullable=True)
    sample_sent_date = Column(Date, nullable=True)
    sample_sent_time = Column(String(20), nullable=True)
    courier_name = Column(String(100), nullable=True)
    tracking_id = Column(String(100), nullable=True)
    franchise_remarks = Column(String(255), nullable=True)
    
    processing_note = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    from sqlalchemy import Index

    __table_args__ = (
        CheckConstraint("age > 0 AND age < 130", name="chk_age_range"),
        CheckConstraint("mobile ~ '^[6-9][0-9]{9}$'", name="chk_patient_mobile"),
        Index("idx_patients_mobile_date", "mobile", "sample_date"),
        Index("idx_patients_collected_by_created", "collected_by", "created_at"),
        Index("idx_patients_name_mobile_code", "name", "mobile", "patient_code"),
        Index("idx_patients_created_active", "created_at", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_patients_code_active", "patient_code", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_patients_mobile_active", "mobile", postgresql_where=text("deleted_at IS NULL")),
    )

    @property
    def amount_due(self):
        effective_total = float(self.total_amount or 0) - float(self.discount_amount or 0)
        return max(0.0, effective_total - float(self.amount_paid or 0))

    @property
    def payment_status(self):
        paid = float(self.amount_paid or 0)
        effective_total = float(self.total_amount or 0) - float(self.discount_amount or 0)
        effective_total = max(0.0, effective_total)
        if paid == 0 and effective_total > 0:
            return "due"
        elif paid >= effective_total:
            return "paid"
        else:
            return "partial"

    # Relationships
    doctor = relationship("Doctor", back_populates="patients")
    collector = relationship("User", foreign_keys=[collected_by], back_populates="patients_collected")
    patient_tests = relationship("PatientTest", back_populates="patient", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="patient")
    status_history = relationship("PatientStatusHistory", back_populates="patient", cascade="all, delete-orphan", order_by="PatientStatusHistory.updated_at.asc()")
    test_results = relationship("PatientTestResult", back_populates="patient", cascade="all, delete-orphan")
