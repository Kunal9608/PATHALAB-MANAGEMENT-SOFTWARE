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
    """FR-2.2 (§2.4) — Save entered result parameters and trigger background PDF generation."""
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")

    saved_total_count = 0
    test_notes_map = {}

    for test_group in payload.tests:
        test_id = test_group.test_id
        if test_group.interpretation_note:
            test_notes_map[str(test_id)] = test_group.interpretation_note

        items = [
            {
                "parameter_id": item.parameter_id,
                "entered_value": item.entered_value,
                "is_abnormal": item.is_abnormal,
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
    """Background task wrapper to run inside a fresh DB session."""
    from backend.app.core.db import SessionLocal
    db = SessionLocal()
    try:
        report_service.generate_and_save_structured_report(db, patient_id, user_id, test_notes_map, partial_release=partial_release, letterhead_mode=letterhead_mode)
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()
