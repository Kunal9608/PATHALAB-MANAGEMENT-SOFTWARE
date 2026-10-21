"""Models package — import all for SQLAlchemy metadata registration."""
from backend.app.models.user import User, RoleEnum, ViewScopeEnum
from backend.app.models.face_embedding import FaceEmbedding
from backend.app.models.attendance_event import AttendanceEvent, EventTypeEnum, AttendanceSourceEnum
from backend.app.models.patient import Patient, GenderEnum, CollectionTypeEnum, PatientStatusEnum
from backend.app.models.patient_test import PatientTest
from backend.app.models.test import Test
from backend.app.models.test_price_history import TestPriceHistory
from backend.app.models.doctor import Doctor
from backend.app.models.franchise import Franchise
from backend.app.models.report import Report
from backend.app.models.expense import Expense, ExpenseCategoryEnum, ExpensePaymentModeEnum
from backend.app.models.login_history import LoginHistory, LoginOutcomeEnum
from backend.app.models.active_session import ActiveSession
from backend.app.models.audit_log import AuditLog
from backend.app.models.otp_request import OtpRequest, OtpPurposeEnum
from backend.app.models.patient_status_history import PatientStatusHistory
from backend.app.models.test_parameter import TestParameter
from backend.app.models.patient_test_result import PatientTestResult
from backend.app.models.cached_patient_registration import CachedPatientRegistration

__all__ = [
    "User", "RoleEnum", "ViewScopeEnum",
    "FaceEmbedding",
    "AttendanceEvent", "EventTypeEnum", "AttendanceSourceEnum",
    "Patient", "GenderEnum", "CollectionTypeEnum", "PatientStatusEnum",
    "PatientTest",
    "Test",
    "TestPriceHistory",
    "Doctor",
    "Franchise",
    "Report",
    "Expense", "ExpenseCategoryEnum", "ExpensePaymentModeEnum",
    "LoginHistory", "LoginOutcomeEnum",
    "ActiveSession",
    "AuditLog",
    "OtpRequest", "OtpPurposeEnum",
    "PatientStatusHistory",
    "TestParameter",
    "PatientTestResult",
    "CachedPatientRegistration",
]
