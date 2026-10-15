"""
Copilot Deterministic Retriever — Backend is the Source of Truth.
Zero Hallucinations, RBAC verification, safe parameterized queries,
Redis-first cache-aside, and strict LookupStatus contract.
"""
import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any, Dict, List, Tuple
from datetime import datetime, time, date, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from sqlalchemy.exc import OperationalError, InterfaceError, SQLAlchemyError

from backend.app.models.user import User, RoleEnum, ViewScopeEnum
from backend.app.models.patient import Patient, PatientStatusEnum
from backend.app.models.report import Report
from backend.app.models.test import Test
from backend.app.models.test_parameter import TestParameter
from backend.app.models.patient_test_result import PatientTestResult
from backend.app.models.patient_test import PatientTest
from backend.app.models.doctor import Doctor
from backend.app.models.expense import Expense
from backend.app.models.audit_log import AuditLog
from backend.app.core import copilot_cache
from backend.app.config import settings

logger = logging.getLogger("akriti.copilot.retriever")

IST = timezone(timedelta(hours=5, minutes=30))


class LookupStatus(str, Enum):
    success = "success"
    not_found = "not_found"
    invalid_input = "invalid_input"
    ambiguous = "ambiguous"
    forbidden = "forbidden"
    service_unavailable = "service_unavailable"
    error = "error"


@dataclass
class BackendLookupResult:
    status: LookupStatus
    entity_type: str
    identifier: Optional[str] = None
    data: Optional[Any] = None
    message: Optional[str] = None
    is_cached: bool = False
    cache_source: Optional[str] = None
    suggestions: Optional[List[str]] = None


# Standard: PAT followed by 6 to 12 digits (e.g. PAT260050, PAT2610000000 for 10M+ scale)
# Legacy:   AKR followed by 6 to 12 digits (e.g. AKR1234567)
PATIENT_ID_EXACT_REGEX = re.compile(r'^(PAT\d{6,12}|AKR\d{6,12})$', re.IGNORECASE)
PATIENT_ID_SCAN_REGEX = re.compile(r'\b(PAT\d{6,12}|AKR\d{6,12})\b', re.IGNORECASE)
# Malformed patient candidate must start with PAT/AKR followed by at least one digit (e.g. PAT12, PAT12345, AKR9)
# Normal English words like "patient", "patients", "pathology", "pathlab" do not contain digits and are never matched.
MALFORMED_PATIENT_SCAN_REGEX = re.compile(r'\b((?:PAT|AKR)[-_]?\d+[A-Z0-9_\-]*)\b', re.IGNORECASE)

RESERVED_WORDS = {
    "PATIENT", "PATIENTS", "PATHOLOGY", "PATHLAB", "PATTERN", "PATTERNS",
    "PATH", "PATHS", "PATCH", "PATCHES", "PATROL"
}

PHONE_EXACT_REGEX = re.compile(r'^[6-9]\d{9}$')
PHONE_SCAN_REGEX = re.compile(r'\b[6-9]\d{9}\b')

TEST_CODE_EXACT_REGEX = re.compile(r'^(TST|TEST)\d{3,6}$', re.IGNORECASE)
TEST_CODE_SCAN_REGEX = re.compile(r'\b((?:TST|TEST)\d{3,6})\b', re.IGNORECASE)


def validate_patient_id(candidate: str) -> Tuple[bool, Optional[str]]:
    """Validates patient code format against production and legacy specifications."""
    normalized = candidate.strip().upper()
    if PATIENT_ID_EXACT_REGEX.match(normalized):
        return True, normalized
    return False, normalized


# ── Core Deterministic Retrieval Functions ─────────────────────────────────────

async def retrieve_patient(
    db: Session,
    patient_code: str,
    current_user: User
) -> BackendLookupResult:
    """
    Deterministic retrieval for a single patient ID.
    Follows: Validate -> Negative Cache -> Redis Cache -> PostgreSQL -> Cache Result.
    """
    is_valid, normalized_id = validate_patient_id(patient_code)
    if not is_valid or not normalized_id:
        return BackendLookupResult(
            status=LookupStatus.invalid_input,
            entity_type="patient",
            identifier=patient_code,
            message=f"Invalid patient ID format: '{patient_code}'. Patient ID must follow format 'PAT' followed by 6-8 digits (e.g. PAT260050) or legacy 'AKR' format."
        )

    # 1. Check Negative Cache
    neg_key = copilot_cache.patient_not_found_key(normalized_id)
    if await copilot_cache.get_negative_cache(neg_key):
        return BackendLookupResult(
            status=LookupStatus.not_found,
            entity_type="patient",
            identifier=normalized_id,
            message=f"No patient record exists with ID {normalized_id} in the current database.",
            is_cached=True,
            cache_source="redis_negative"
        )

    # 2. Check Scoped Redis Cache
    scope = "all" if getattr(current_user, 'role', None) == RoleEnum.admin or getattr(current_user, 'view_scope', None) == ViewScopeEnum.all else f"user:{current_user.id}"
    cache_key = copilot_cache.patient_key(normalized_id, scope)
    cached_data = await copilot_cache.get_cached(cache_key)
    if cached_data is not None:
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="patient",
            identifier=normalized_id,
            data=cached_data,
            is_cached=True,
            cache_source="redis"
        )

    # 3. Query PostgreSQL with Safe Parameterized Lookup
    try:
        query = db.query(Patient).filter(
            Patient.patient_code == normalized_id,
            Patient.deleted_at.is_(None)
        )
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)

        patient = query.first()

    except (OperationalError, InterfaceError) as e:
        logger.error(f"PostgreSQL connection/operational failure during patient lookup: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="patient",
            identifier=normalized_id,
            message="Database connection error. Unable to verify patient records. Please try again in a few moments."
        )
    except SQLAlchemyError as e:
        logger.error(f"PostgreSQL query error during patient lookup: {e}")
        return BackendLookupResult(
            status=LookupStatus.error,
            entity_type="patient",
            identifier=normalized_id,
            message="Internal database error occurred while retrieving patient record."
        )

    # 4. Handle Not Found vs Forbidden
    if not patient:
        # Check if record exists under another staff member's scope (Forbidden vs Not Found)
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            try:
                exists_elsewhere = db.query(Patient.id).filter(
                    Patient.patient_code == normalized_id,
                    Patient.deleted_at.is_(None)
                ).first()
                if exists_elsewhere:
                    return BackendLookupResult(
                        status=LookupStatus.forbidden,
                        entity_type="patient",
                        identifier=normalized_id,
                        message="You do not have permission to access this patient record."
                    )
            except Exception:
                pass

        # Authoritative Not Found confirmed: Set negative cache to protect DB
        await copilot_cache.set_negative_cache(neg_key, ttl=settings.REDIS_NEGATIVE_TTL)
        return BackendLookupResult(
            status=LookupStatus.not_found,
            entity_type="patient",
            identifier=normalized_id,
            message=f"No patient record exists with ID {normalized_id} in the current database."
        )

    # 5. Extract Structured Authorized Patient Data
    structured_patient = _extract_patient_details(db, patient)

    # 6. Cache Valid Result in Redis
    await copilot_cache.set_cached(cache_key, structured_patient, ttl=settings.REDIS_DEFAULT_TTL)

    return BackendLookupResult(
        status=LookupStatus.success,
        entity_type="patient",
        identifier=normalized_id,
        data=structured_patient,
        is_cached=False,
        cache_source="postgresql"
    )


async def retrieve_by_phone(
    db: Session,
    phone_number: str,
    current_user: User
) -> BackendLookupResult:
    """Retrieve patient records associated with a verified 10-digit mobile number."""
    if not PHONE_EXACT_REGEX.match(phone_number):
        return BackendLookupResult(
            status=LookupStatus.invalid_input,
            entity_type="phone",
            identifier=phone_number,
            message=f"Invalid mobile number format: '{phone_number}'. Must be a 10-digit number starting with 6-9."
        )

    scope = "all" if getattr(current_user, 'role', None) == RoleEnum.admin or getattr(current_user, 'view_scope', None) == ViewScopeEnum.all else f"user:{current_user.id}"
    cache_key = copilot_cache.phone_key(phone_number, scope)
    cached_data = await copilot_cache.get_cached(cache_key)
    if cached_data is not None:
        return BackendLookupResult(
            status=LookupStatus.success if cached_data else LookupStatus.not_found,
            entity_type="phone",
            identifier=phone_number,
            data=cached_data,
            is_cached=True,
            cache_source="redis"
        )

    try:
        query = db.query(Patient).filter(
            Patient.mobile == phone_number,
            Patient.deleted_at.is_(None)
        )
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)

        patients = query.order_by(Patient.created_at.desc()).limit(10).all()
    except (OperationalError, InterfaceError) as e:
        logger.error(f"PostgreSQL failure during phone search: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="phone",
            identifier=phone_number,
            message="Database connection error. Unable to verify records. Please try again."
        )

    if not patients:
        await copilot_cache.set_cached(cache_key, [], ttl=settings.REDIS_NEGATIVE_TTL)
        return BackendLookupResult(
            status=LookupStatus.not_found,
            entity_type="phone",
            identifier=phone_number,
            message=f"No patient records found associated with mobile number {phone_number}."
        )

    structured_list = [_extract_patient_details(db, p) for p in patients]
    await copilot_cache.set_cached(cache_key, structured_list, ttl=settings.REDIS_DEFAULT_TTL)

    return BackendLookupResult(
        status=LookupStatus.success,
        entity_type="phone",
        identifier=phone_number,
        data=structured_list,
        is_cached=False,
        cache_source="postgresql"
    )


async def retrieve_test(
    db: Session,
    test_code: str
) -> BackendLookupResult:
    """Retrieve test catalog information by test code."""
    norm_code = test_code.strip().upper()
    cache_key = copilot_cache.test_key(norm_code)
    cached_data = await copilot_cache.get_cached(cache_key)
    if cached_data is not None:
        return BackendLookupResult(
            status=LookupStatus.success if cached_data else LookupStatus.not_found,
            entity_type="test",
            identifier=norm_code,
            data=cached_data,
            is_cached=True,
            cache_source="redis"
        )

    try:
        test = db.query(Test).filter(Test.test_code == norm_code).first()
    except Exception as e:
        logger.error(f"Database error during test lookup: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="test",
            identifier=norm_code,
            message="Database connection error while retrieving test information."
        )

    if not test:
        await copilot_cache.set_cached(cache_key, {}, ttl=settings.REDIS_NEGATIVE_TTL)
        return BackendLookupResult(
            status=LookupStatus.not_found,
            entity_type="test",
            identifier=norm_code,
            message=f"No laboratory test exists with code '{norm_code}'."
        )

    test_data = {
        "test_code": str(getattr(test, 'test_code', norm_code)),
        "name": str(getattr(test, 'name', '')),
        "price": float(getattr(test, 'price', 0)),
        "category": str(getattr(test, 'category', '')),
        "is_active": bool(getattr(test, 'is_active', True)),
        "parameters": [str(p.parameter_name) for p in test.parameters] if getattr(test, 'parameters', None) else []
    }
    await copilot_cache.set_cached(cache_key, test_data, ttl=settings.REDIS_DEFAULT_TTL)

    return BackendLookupResult(
        status=LookupStatus.success,
        entity_type="test",
        identifier=norm_code,
        data=test_data,
        is_cached=False,
        cache_source="postgresql"
    )


async def retrieve_finance(
    db: Session,
    current_user: User,
    specific_date: Optional[date] = None
) -> BackendLookupResult:
    """Compute exact financial revenue, expenses, and profit. ADMIN ONLY."""
    if getattr(current_user, 'role', None) != RoleEnum.admin:
        return BackendLookupResult(
            status=LookupStatus.forbidden,
            entity_type="finance",
            message="You do not have permission to access financial information."
        )

    date_str = specific_date.isoformat() if specific_date else date.today().isoformat()
    cache_key = copilot_cache.finance_key(date_str, "admin")
    cached = await copilot_cache.get_cached(cache_key)
    if cached is not None:
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="finance",
            data=cached,
            is_cached=True,
            cache_source="redis"
        )

    try:
        now = datetime.now()
        today_start = datetime.combine(now.date(), time.min)
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_start
        month_start = today_start.replace(day=1)

        today_rev = db.query(func.sum(Patient.amount_paid)).filter(Patient.created_at >= today_start, Patient.deleted_at.is_(None)).scalar() or 0
        yesterday_rev = db.query(func.sum(Patient.amount_paid)).filter(Patient.created_at >= yesterday_start, Patient.created_at < yesterday_end, Patient.deleted_at.is_(None)).scalar() or 0
        month_rev = db.query(func.sum(Patient.amount_paid)).filter(Patient.created_at >= month_start, Patient.deleted_at.is_(None)).scalar() or 0
        total_rev = db.query(func.sum(Patient.amount_paid)).filter(Patient.deleted_at.is_(None)).scalar() or 0

        today_exp = db.query(func.sum(Expense.amount)).filter(Expense.created_at >= today_start).scalar() or 0
        yesterday_exp = db.query(func.sum(Expense.amount)).filter(Expense.created_at >= yesterday_start, Expense.created_at < yesterday_end).scalar() or 0
        month_exp = db.query(func.sum(Expense.amount)).filter(Expense.created_at >= month_start).scalar() or 0
        total_exp = db.query(func.sum(Expense.amount)).scalar() or 0

        data: Dict[str, Any] = {
            "today_revenue": float(today_rev),
            "today_expense": float(today_exp),
            "today_net": float(today_rev - today_exp),
            "yesterday_revenue": float(yesterday_rev),
            "yesterday_expense": float(yesterday_exp),
            "yesterday_net": float(yesterday_rev - yesterday_exp),
            "month_revenue": float(month_rev),
            "month_expense": float(month_exp),
            "month_net": float(month_rev - month_exp),
            "total_revenue": float(total_rev),
            "total_expense": float(total_exp),
            "total_net": float(total_rev - total_exp),
        }

        if specific_date:
            s_start = datetime.combine(specific_date, time.min)
            s_end = s_start + timedelta(days=1)
            s_rev = db.query(func.sum(Patient.amount_paid)).filter(Patient.created_at >= s_start, Patient.created_at < s_end, Patient.deleted_at.is_(None)).scalar() or 0
            data["specific_date"] = specific_date.isoformat()
            data["specific_date_revenue"] = float(s_rev)

        await copilot_cache.set_cached(cache_key, data, ttl=settings.REDIS_FINANCE_TTL)
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="finance",
            data=data,
            is_cached=False,
            cache_source="postgresql"
        )
    except Exception as e:
        logger.error(f"Finance calculation error: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="finance",
            message="Database connection error while computing financial analytics."
        )


async def retrieve_pending_reports(
    db: Session,
    current_user: User
) -> BackendLookupResult:
    """Retrieve pending patient reports with RBAC scope."""
    scope = "all" if getattr(current_user, 'role', None) == RoleEnum.admin or getattr(current_user, 'view_scope', None) == ViewScopeEnum.all else f"user:{current_user.id}"
    cache_key = copilot_cache.pending_reports_key(scope)
    cached = await copilot_cache.get_cached(cache_key)
    if cached is not None:
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="pending_reports",
            data=cached,
            is_cached=True,
            cache_source="redis"
        )

    try:
        query = db.query(Patient).filter(
            Patient.status != PatientStatusEnum.report_ready,
            Patient.deleted_at.is_(None)
        )
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)

        pending_patients = query.order_by(Patient.created_at.desc()).limit(15).all()
        pending_list = []
        for p in pending_patients:
            status_str = p.status.value if hasattr(p.status, 'value') else str(p.status)
            p_date = getattr(p, 'sample_date', None)
            pending_list.append({
                "patient_code": p.patient_code,
                "name": p.name,
                "status": status_str,
                "date": str(p_date) if p_date else "N/A"
            })

        await copilot_cache.set_cached(cache_key, pending_list, ttl=settings.REDIS_DEFAULT_TTL)
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="pending_reports",
            data=pending_list,
            is_cached=False,
            cache_source="postgresql"
        )
    except Exception as e:
        logger.error(f"Error retrieving pending reports: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="pending_reports",
            message="Database error occurred while fetching pending reports."
        )


# ── Helper to format authorized patient details ────────────────────────────────

def _extract_patient_details(db: Session, patient: Patient) -> Dict[str, Any]:
    p: Any = patient
    # Doctor info
    doc_name = "Self"
    if p.doctor_id:
        doc = db.query(Doctor).filter(Doctor.id == p.doctor_id).first()
        if doc:
            doc_name = f"Dr. {doc.name}"

    # Collector info
    collector_name = "System"
    if p.collected_by:
        col = db.query(User).filter(User.id == p.collected_by).first()
        if col:
            collector_name = col.name

    # Reports — Retrieve ONLY the single latest report (e.g. latest version)
    reports_data = []
    reports = db.query(Report).filter(
        Report.patient_id == p.id
    ).order_by(Report.version.desc(), Report.uploaded_at.desc()).all()
    if reports:
        # Prefer the report marked is_latest=True, or fallback to the top version
        latest_r = next((r for r in reports if getattr(r, 'is_latest', False)), reports[0])
        r_up = getattr(latest_r, 'uploaded_at', None)
        uploaded_str = "N/A"
        if r_up:
            if r_up.tzinfo is None:
                r_up = r_up.replace(tzinfo=timezone.utc)
            uploaded_str = r_up.astimezone(IST).strftime('%d %b %Y, %I:%M %p')

        v_num = getattr(latest_r, 'version', 1)
        reports_data.append({
            "id": str(latest_r.id),
            "version": v_num,
            "version_label": f"v{v_num}" if v_num else "Latest",
            "is_latest": True,
            "uploaded_at": uploaded_str,
            "download_url": f"/api/v1/reports/download/{latest_r.id}?action=view"
        })

    # Booked Tests
    booked_tests = []
    patient_tests = db.query(PatientTest).filter(PatientTest.patient_id == p.id).all()
    for pt in patient_tests:
        pt_test = getattr(pt, 'test', None)
        t_name = pt_test.name if pt_test else "Test"
        price_snap = float(getattr(pt, 'price_at_booking', 0))
        booked_tests.append(f"{t_name} (Rs {price_snap})")

    # Test Results
    results_data = []
    test_results = db.query(PatientTestResult).filter(PatientTestResult.patient_id == p.id).all()
    for tr in test_results:
        param = db.query(TestParameter).filter(TestParameter.id == tr.parameter_id).first()
        if param:
            results_data.append({
                "parameter": param.parameter_name,
                "value": tr.entered_value,
                "unit": param.unit or "",
                "is_abnormal": tr.is_abnormal
            })

    gender_val = p.gender.value if hasattr(p.gender, 'value') else str(p.gender)
    status_val = p.status.value if hasattr(p.status, 'value') else str(p.status)
    s_date = getattr(p, 'sample_date', None)

    return {
        "id": str(p.id),
        "patient_code": str(p.patient_code),
        "name": str(p.name),
        "age": int(p.age),
        "gender": gender_val,
        "mobile": str(p.mobile),
        "status": status_val,
        "sample_date": str(s_date) if s_date else "N/A",
        "total_amount": float(p.total_amount or 0),
        "discount_amount": float(p.discount_amount or 0),
        "amount_paid": float(p.amount_paid or 0),
        "amount_due": float(p.amount_due or 0),
        "payment_status": str(p.payment_status),
        "referred_by": doc_name,
        "collected_by": collector_name,
        "booked_tests": booked_tests,
        "reports": reports_data,
        "test_results": results_data
    }


async def retrieve_latest_reports(
    db: Session,
    current_user: User,
    limit: int = 5
) -> BackendLookupResult:
    """
    Retrieves the most recent released diagnostic reports with full patient details.
    Enforces RBAC: Staff only see their own patients unless view_scope == all.
    """
    cache_key = f"copilot:v1:latest_reports:role_{current_user.role}:scope_{current_user.view_scope}:user_{current_user.id}"
    cached_data = await copilot_cache.get_cached(cache_key)
    if cached_data is not None:
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="latest_reports",
            data=cached_data,
            is_cached=True,
            cache_source="redis"
        )

    try:
        # Check Report table first
        query = db.query(Report).join(Patient, Report.patient_id == Patient.id).filter(
            Patient.deleted_at.is_(None)
        )
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)

        reports = query.order_by(Report.uploaded_at.desc()).limit(limit).all()

        results_list = []
        if reports:
            for r in reports:
                p = r.patient
                p_details = _extract_patient_details(db, p)
                p_details["latest_report_id"] = str(r.id)
                p_details["latest_report_version"] = getattr(r, 'version', 1)
                r_up = getattr(r, 'uploaded_at', None)
                if r_up:
                    if r_up.tzinfo is None:
                        r_up = r_up.replace(tzinfo=timezone.utc)
                    p_details["latest_report_uploaded_at"] = r_up.astimezone(IST).strftime('%d %b %Y, %I:%M %p')
                else:
                    p_details["latest_report_uploaded_at"] = "N/A"
                p_details["latest_report_url"] = f"/api/v1/reports/download/{r.id}?action=view"
                results_list.append(p_details)
        else:
            # Fallback to patients with status == report_ready
            p_query = db.query(Patient).filter(
                Patient.deleted_at.is_(None),
                Patient.status == PatientStatusEnum.report_ready
            )
            if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
                p_query = p_query.filter(Patient.collected_by == current_user.id)
            ready_patients = p_query.order_by(Patient.updated_at.desc()).limit(limit).all()
            for p in ready_patients:
                results_list.append(_extract_patient_details(db, p))

        await copilot_cache.set_cached(cache_key, results_list, ttl=settings.REDIS_DEFAULT_TTL)
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="latest_reports",
            data=results_list,
            is_cached=False,
            cache_source="postgresql"
        )
    except Exception as e:
        logger.error(f"Error retrieving latest reports: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="latest_reports",
            message="Database error occurred while fetching latest reports."
        )


async def retrieve_latest_patient(
    db: Session,
    current_user: User
) -> BackendLookupResult:
    """
    Retrieves the most recently registered patient in the database.
    """
    try:
        query = db.query(Patient).filter(Patient.deleted_at.is_(None))
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)

        last_patient = query.order_by(Patient.created_at.desc()).first()
        if not last_patient:
            return BackendLookupResult(
                status=LookupStatus.not_found,
                entity_type="patient",
                message="No patient records found in the system."
            )
        data = _extract_patient_details(db, last_patient)
        return BackendLookupResult(
            status=LookupStatus.success,
            entity_type="patient",
            identifier=str(last_patient.patient_code),
            data=data
        )
    except Exception as e:
        logger.error(f"Error retrieving latest patient: {e}")
        return BackendLookupResult(
            status=LookupStatus.service_unavailable,
            entity_type="patient",
            message="Database error occurred while fetching recent patient."
        )
