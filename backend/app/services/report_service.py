"""Report service — upload, digital signature, verification hash."""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from backend.app.models.report import Report
from backend.app.models.patient import Patient, PatientStatusEnum
from backend.app.repositories import patient_repo
from backend.app.services import audit_service, notification_service

REPORTS_DIR = Path("uploads/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_safe_filename(original_filename: str, prefix: str) -> str:
    import re
    import os
    import uuid
    orig_base, orig_ext = os.path.splitext(original_filename)
    sanitized_base = re.sub(r'[^a-zA-Z0-9_-]', '_', orig_base)
    return f"{prefix}_{uuid.uuid4().hex[:8]}_{sanitized_base}{orig_ext}"


def upload_report(db: Session, patient_id: uuid.UUID, file_bytes: bytes,
                  filename: str, uploader_id: uuid.UUID, background_tasks,
                  reason: Optional[str] = None, force: bool = False, source: str = "manual",
                  partial_release: bool = False) -> dict:
    """FR-7.1 — Upload report PDF, compute hash, update patient status."""
    # Acquire row-level lock on patient to serialize concurrent report uploads and avoid race in version allocation
    patient = db.query(Patient).filter(Patient.id == patient_id).with_for_update().first()
    if not patient:
        raise ValueError("Patient not found")

    # Compute verification hash (SHA-256 of file content)
    verification_hash = hashlib.sha256(file_bytes).hexdigest()

    # Check for identical duplicate file content
    if not force:
        existing = db.query(Report).options(joinedload(Report.uploader)).filter(
            Report.patient_id == patient_id,
            Report.verification_hash == verification_hash
        ).first()
        if existing:
            uploader_name = existing.uploader.name if existing.uploader else "Unknown"
            raise ValueError(f"DUPLICATE_REPORT:An identical report was already uploaded as Version {existing.version} by {uploader_name}.")

    # Mark previous reports as not latest
    db.query(Report).filter(Report.patient_id == patient_id).update({"is_latest": False})

    # Get version number
    version = db.query(Report).filter(Report.patient_id == patient_id).count() + 1

    safe_filename = generate_safe_filename(filename, f"{patient.patient_code}_v{version}")

    from backend.app.core.storage import upload_file_bytes, delete_file_object
    db_file_path = None
    try:
        db_file_path = upload_file_bytes(
            file_bytes=file_bytes,
            filename=safe_filename,
            content_type="application/pdf",
            folder="reports"
        )

        report = Report(
            patient_id=patient_id,
            file_path=db_file_path,
            original_filename=filename,
            signed=False,
            verification_hash=verification_hash,
            version=version,
            source=source,
            uploaded_by=uploader_id,
            is_latest=True,
        )
        db.add(report)
        db.flush()

        # Update patient status
        target_status = PatientStatusEnum.partial_release if partial_release else PatientStatusEnum.report_ready
        patient_repo.update_patient(db, patient_id, status=target_status)

        # Log report upload in patient status history
        from backend.app.models.patient_status_history import PatientStatusHistory
        history = PatientStatusHistory(
            patient_id=patient_id,
            status=target_status.value if hasattr(target_status, 'value') else str(target_status),
            updated_by=uploader_id,
            extra_info={"version": version, "filename": filename, "reason": reason}
        )
        db.add(history)

        audit_service.log(db, "report.upload", actor_user_id=uploader_id,
                          entity_type="report", entity_id=report.id,
                          after={"patient_code": patient.patient_code, "version": version})
        db.commit()
    except Exception as exc:
        db.rollback()
        # Compensating cleanup: remove uploaded object/file on DB failure
        if db_file_path:
            delete_file_object(db_file_path)
        raise exc
    try:
        from backend.app.core import copilot_cache
        copilot_cache.invalidate_patient_sync(str(patient.patient_code))
    except Exception:
        pass

    # Notify using BackgroundTasks (fire-and-forget)
    from backend.app.config import settings
    recipient = settings.MAIL_FROM or settings.MAIL_USERNAME or "lab@akriti.com"
    attachment_name = f"report_{patient.patient_code}.pdf"
    reg_date_str = (
        patient.sample_date.strftime("%d %b %Y") if patient.sample_date
        else (patient.created_at.strftime("%d %b %Y") if getattr(patient, "created_at", None) else "")
    )
    background_tasks.add_task(
        notification_service.notify,
        "report_ready",
        recipient,
        {
            "patient_name": patient.name,
            "patient_code": patient.patient_code,
            "age": patient.age,
            "registered_date": reg_date_str,
            "attachment_bytes": file_bytes,
            "attachment_name": attachment_name,
            "mobile": patient.mobile,
            "report_id": str(report.id),
        }
    )

    return {
        "id": str(report.id),
        "patient_code": patient.patient_code,
        "version": version,
        "verification_hash": verification_hash,
        "uploaded_at": report.uploaded_at.isoformat(),
    }


def get_patient_reports(db: Session, patient_id: uuid.UUID) -> list:
    reports = (
        db.query(Report)
        .options(joinedload(Report.uploader))
        .filter(Report.patient_id == patient_id)
        .order_by(Report.version.desc())
        .all()
    )
    return [
        {
            "id": str(r.id),
            "version": r.version,
            "filename": r.original_filename,
            "signed": r.signed,
            "verification_hash": r.verification_hash,
            "is_latest": r.is_latest,
            "source": getattr(r, "source", "manual") or "manual",
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None,
            "uploaded_by_name": r.uploader.name if r.uploader else "Unknown",
        }
        for r in reports
    ]


def verify_report(db: Session, report_id: uuid.UUID, short_hash: Optional[str] = None) -> dict:
    """Public verification endpoint — requires exact full hash or high-entropy verification token."""
    import hmac
    if not short_hash or len(short_hash.strip()) < 16:
        return {
            "verified": False,
            "message": "Verification requires a valid 16+ character hash token"
        }

    clean_token = short_hash.strip().lower()
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report or not report.verification_hash:
        return {"verified": False, "message": "Report record or verification hash not found"}

    expected_hash = report.verification_hash.lower()
    matches = False
    if len(clean_token) == len(expected_hash):
        matches = hmac.compare_digest(clean_token, expected_hash)
    elif len(clean_token) >= 32 and expected_hash.startswith(clean_token):
        matches = hmac.compare_digest(clean_token, expected_hash[:len(clean_token)])

    if not matches:
        return {"verified": False, "message": "Invalid verification token — authenticity cannot be confirmed"}

    return {
        "verified": True,
        "report_version": report.version,
        "issued_on": report.uploaded_at.strftime("%d %B %Y") if report.uploaded_at else "Unknown",
        "message": "Verified authentic — officially issued by Akriti Diagnostics Center",
    }


def generate_and_save_structured_report(db: Session, patient_id: uuid.UUID, uploader_id: uuid.UUID, test_notes_map: Optional[dict] = None, partial_release: bool = False, letterhead_mode: bool = False) -> dict:
    """Generate official PDF from entered patient_test_results and save as new version with source='auto'."""
    from backend.app.models.patient_test_result import PatientTestResult
    from backend.app.services.structured_report_pdf import generate_structured_report_pdf

    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")

    if not test_notes_map:
        test_notes_map = {}

    from collections import defaultdict
    
    # Eagerly load all test results and their parameters in a single query (fixes N+1)
    all_results = db.query(PatientTestResult).options(
        joinedload(PatientTestResult.parameter)
    ).filter(
        PatientTestResult.patient_id == patient_id
    ).all()
    
    results_by_test = defaultdict(list)
    for r in all_results:
        results_by_test[r.test_id].append(r)

    booked_tests_data = []
    for pt in patient.patient_tests:
        test_obj = pt.test
        if not test_obj:
            continue

        results = results_by_test.get(test_obj.id, [])

        params_list = []
        for r in results:
            param = r.parameter
            if not param:
                continue
            ref_str = param.reference_text
            if not ref_str and param.reference_low is not None and param.reference_high is not None:
                ref_str = f"{param.reference_low} - {param.reference_high}"
            params_list.append({
                "name": param.parameter_name,
                "value": r.entered_value,
                "unit": param.unit or "",
                "reference": ref_str or "",
                "is_abnormal": r.is_abnormal,
                "display_order": param.display_order
            })

        params_list.sort(key=lambda x: x["display_order"])
        booked_tests_data.append({
            "test_name": test_obj.name,
            "interpretation_note": test_notes_map.get(str(test_obj.id), ""),
            "parameters": params_list
        })

    pdf_bytes = generate_structured_report_pdf(patient, booked_tests_data, letterhead_mode=letterhead_mode)
    filename = f"Report_{patient.patient_code}_Structured.pdf"

    # Use a dummy BackgroundTasks instance that delegates to a background thread
    class DummyBackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            import threading
            def _run():
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    import logging
                    logging.getLogger("akriti.reports").error(f"Failed notification dispatch: {e}")
            threading.Thread(target=_run, daemon=True).start()

    return upload_report(
        db, patient_id, pdf_bytes, filename, uploader_id, DummyBackgroundTasks(),
        reason="Automated structured report generation", force=True, source="auto", partial_release=partial_release
    )


def generate_patient_report_pdf_bytes(db: Session, patient_id: uuid.UUID, letterhead_mode: bool = False) -> bytes:
    """Generate official PDF bytes for patient on-the-fly. If letterhead_mode=True, includes digital lab header (for WhatsApp)."""
    from backend.app.models.patient_test_result import PatientTestResult
    from backend.app.services.structured_report_pdf import generate_structured_report_pdf
    from collections import defaultdict
    from sqlalchemy.orm import joinedload

    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")

    all_results = db.query(PatientTestResult).options(
        joinedload(PatientTestResult.parameter)
    ).filter(
        PatientTestResult.patient_id == patient_id
    ).all()

    results_by_test = defaultdict(list)
    for r in all_results:
        results_by_test[r.test_id].append(r)

    booked_tests_data = []
    for pt in (patient.patient_tests or []):
        test_obj = pt.test
        if not test_obj:
            continue

        results = results_by_test.get(test_obj.id, [])
        params_list = []
        for r in results:
            param = r.parameter
            if not param:
                continue
            ref_str = param.reference_text
            if not ref_str and param.reference_low is not None and param.reference_high is not None:
                ref_str = f"{param.reference_low} - {param.reference_high}"
            params_list.append({
                "name": param.parameter_name,
                "value": r.entered_value,
                "unit": param.unit or "",
                "reference": ref_str or "",
                "is_abnormal": r.is_abnormal,
                "display_order": param.display_order
            })

        params_list.sort(key=lambda x: x["display_order"])
        booked_tests_data.append({
            "test_name": test_obj.name,
            "interpretation_note": "",
            "parameters": params_list
        })

    return generate_structured_report_pdf(patient, booked_tests_data, letterhead_mode=letterhead_mode)

