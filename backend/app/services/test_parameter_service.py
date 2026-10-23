"""Service for managing test parameter catalog and submitting report entries (§2.1 / §2.2 / §2.4)."""
import uuid
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from backend.app.repositories import test_parameter_repo, patient_repo, test_repo
from backend.app.models.test import Test
from backend.app.models.test_parameter import TestParameter
from backend.app.schemas.test_parameter import TestParameterCreate, TestParameterBulkSave
from backend.app.schemas.report_entry import ReportEntrySubmit
from backend.app.services import audit_service, report_service


def get_test_parameters(db: Session, test_id: uuid.UUID) -> List[TestParameter]:
    return test_parameter_repo.get_by_test_id(db, test_id)


def save_test_parameters(db: Session, test_id: uuid.UUID, payload: TestParameterBulkSave, admin_id: uuid.UUID) -> List[TestParameter]:
    test = test_repo.get_test_by_id(db, test_id)
    if not test:
        raise ValueError("Test not found")

    new_params = test_parameter_repo.replace_for_test(db, test_id, payload.parameters)
    audit_service.log(
        db, "test.parameters.update",
        actor_user_id=admin_id,
        entity_type="test",
        entity_id=test_id,
        after={"count": len(new_params)}
    )
    db.commit()
    return new_params


def submit_report_entry(db: Session, patient_id: uuid.UUID, payload: ReportEntrySubmit,
                        user_id: uuid.UUID, background_tasks, partial_release: bool = False, letterhead_mode: bool = False) -> Dict[str, Any]:
    """FR-2.2 (§2.4) — Save entered result parameters and trigger background PDF generation with strict ownership checks."""
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient or getattr(patient, "deleted_at", None) is not None:
        raise ValueError("Patient not found or inactive")

    if not payload.tests:
        raise ValueError("No test results submitted")

    # 1. Enforce uniqueness across submitted test groups
    submitted_test_ids = [tg.test_id for tg in payload.tests]
    if len(submitted_test_ids) != len(set(submitted_test_ids)):
        raise ValueError("Duplicate test groups submitted in payload")

    # 2. Enforce that every submitted test is booked by this patient
    booked_test_ids = {pt.test_id for pt in (patient.patient_tests or [])}
    unbooked = set(submitted_test_ids) - booked_test_ids
    if unbooked:
        raise ValueError(f"Integrity violation: Submitted tests are not booked for this patient: {unbooked}")

    # 3. Enforce parameter uniqueness per test group
    for test_group in payload.tests:
        p_ids = [item.parameter_id for item in test_group.results]
        if len(p_ids) != len(set(p_ids)):
            raise ValueError(f"Duplicate parameter entries submitted for test {test_group.test_id}")

    saved_total_count = 0
    test_notes_map = {}

    # 4. Atomic execution across all tests
    for test_group in payload.tests:
        test_id = test_group.test_id
        if test_group.interpretation_note:
            test_notes_map[str(test_id)] = test_group.interpretation_note

        items = [
            {
                "parameter_id": item.parameter_id,
                "entered_value": item.entered_value,
                "interpretation_note": item.interpretation_note,
            }
            for item in test_group.results
        ]
        saved = test_parameter_repo.save_patient_test_results(db, patient_id, test_id, items, user_id)
        saved_total_count += len(saved)

    audit_service.log(
        db, "report.entry.submit",
        actor_user_id=user_id,
        entity_type="patient",
        entity_id=patient_id,
        after={"saved_results_count": saved_total_count, "partial_release": partial_release}
    )
    db.commit()

    try:
        from backend.app.core import copilot_cache
        copilot_cache.invalidate_patient_sync(str(patient.patient_code))
    except Exception:
        pass

    # Queue background task for PDF generation
    background_tasks.add_task(
        _background_generate_report,
        patient_id=patient_id,
        user_id=user_id,
        test_notes_map=test_notes_map,
        partial_release=partial_release,
        letterhead_mode=letterhead_mode
    )

    return {
        "status": "queued",
        "message": "Report results saved successfully. PDF generation queued in background." + (" (Partial Release)" if partial_release else ""),
        "patient_code": patient.patient_code,
        "saved_results_count": saved_total_count,
        "partial_release": partial_release
    }


def _background_generate_report(patient_id: uuid.UUID, user_id: uuid.UUID, test_notes_map: Dict[str, str], partial_release: bool = False, letterhead_mode: bool = False):
    """Background task wrapper with error tracking and durable status logging."""
    from backend.app.core.db import SessionLocal
    import logging
    logger = logging.getLogger("akriti.reports")
    db = SessionLocal()
    try:
        report_service.generate_and_save_structured_report(
            db, patient_id, user_id, test_notes_map,
            partial_release=partial_release, letterhead_mode=letterhead_mode
        )
    except Exception as e:
        logger.error(f"Background PDF report generation failed for patient {patient_id}: {e}", exc_info=True)
        try:
            from backend.app.models.patient_status_history import PatientStatusHistory
            h = PatientStatusHistory(
                patient_id=patient_id,
                status="report_generation_failed",
                updated_by=user_id,
                extra_info={"error": "PDF generation failed in background task"}
            )
            db.add(h)
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
