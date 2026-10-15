"""Repository for TestParameter and PatientTestResult."""
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import re

from backend.app.models.test_parameter import TestParameter
from backend.app.models.patient_test_result import PatientTestResult
from backend.app.schemas.test_parameter import TestParameterCreate


def get_by_test_id(db: Session, test_id: uuid.UUID) -> List[TestParameter]:
    return (
        db.query(TestParameter)
        .filter(TestParameter.test_id == test_id)
        .order_by(TestParameter.display_order.asc())
        .all()
    )


def replace_for_test(db: Session, test_id: uuid.UUID, parameters_data: List[TestParameterCreate]) -> List[TestParameter]:
    # Delete existing parameters for the test
    db.query(TestParameter).filter(TestParameter.test_id == test_id).delete()

    new_params = []
    for item in parameters_data:
        ref_low = item.reference_low
        ref_high = item.reference_high

        if item.input_type == "numeric" and item.reference_text and ref_low is None and ref_high is None:
            # Try to extract numbers from formats like "10-20", "10.5 - 20.5"
            match = re.search(r"([\d\.]+)\s*-\s*([\d\.]+)", item.reference_text)
            if match:
                try:
                    ref_low = float(match.group(1))
                    ref_high = float(match.group(2))
                except ValueError:
                    pass

        p = TestParameter(
            test_id=test_id,
            parameter_name=item.parameter_name,
            unit=item.unit,
            input_type=item.input_type,
            dropdown_options=item.dropdown_options,
            reference_low=ref_low,
            reference_high=ref_high,
            reference_text=item.reference_text,
            applicable_gender=item.applicable_gender,
            display_order=item.display_order,
        )
        db.add(p)
        new_params.append(p)

    db.flush()
    return new_params


def get_patient_test_results(db: Session, patient_id: uuid.UUID) -> List[PatientTestResult]:
    return (
        db.query(PatientTestResult)
        .filter(PatientTestResult.patient_id == patient_id)
        .all()
    )


def save_patient_test_results(db: Session, patient_id: uuid.UUID, test_id: uuid.UUID,
                              results: list, entered_by: uuid.UUID) -> List[PatientTestResult]:
    """Save result items for a given test in a patient report entry."""
    # Delete existing results for this patient and test so re-submission cleanly updates
    db.query(PatientTestResult).filter(
        PatientTestResult.patient_id == patient_id,
        PatientTestResult.test_id == test_id
    ).delete()

    saved_items = []
    # Batch pre-fetch all parameters in one query to eliminate N+1 round trips
    param_ids = [item["parameter_id"] for item in results if "parameter_id" in item]
    param_map = {}
    if param_ids:
        params = db.query(TestParameter).filter(TestParameter.id.in_(param_ids)).all()
        param_map = {p.id: p for p in params}

    for item in results:
        # Determine is_abnormal
        param = param_map.get(item["parameter_id"])
        is_abnormal = False
        if item.get("is_abnormal") is not None:
            is_abnormal = bool(item["is_abnormal"])
        elif param and param.input_type == "numeric" and item["entered_value"]:
            try:
                val = float(item["entered_value"])
                if param.reference_low is not None and val < float(param.reference_low):
                    is_abnormal = True
                if param.reference_high is not None and val > float(param.reference_high):
                    is_abnormal = True
            except ValueError:
                pass

        r = PatientTestResult(
            patient_id=patient_id,
            test_id=test_id,
            parameter_id=item["parameter_id"],
            entered_value=item["entered_value"],
            is_abnormal=is_abnormal,
            interpretation_note=item.get("interpretation_note"),
            entered_by=entered_by,
        )
        db.add(r)
        saved_items.append(r)

    db.flush()
    return saved_items
