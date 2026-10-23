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


def calculate_is_abnormal(param: Optional[TestParameter], val_str: str) -> bool:
    """Authoritative server-side calculation of is_abnormal — never trust client flag."""
    if not param or not val_str:
        return False
    val_str = str(val_str).strip()
    if param.input_type == "numeric":
        try:
            val = float(val_str)
            if param.reference_low is not None and val < float(param.reference_low):
                return True
            if param.reference_high is not None and val > float(param.reference_high):
                return True
        except ValueError:
            return False
    elif param.input_type in ("options", "dropdown", "select", "text", "multiline", "serology"):
        ref_text = getattr(param, "reference_text", None) or getattr(param, "reference_range", None)
        if ref_text:
            val_lower = val_str.lower()
            ref_lower = str(ref_text).lower()
            if "negative" in ref_lower and ("positive" in val_lower or "reactive" in val_lower):
                return True
            if "non-reactive" in ref_lower and "reactive" in val_lower and "non-reactive" not in val_lower:
                return True
    return False


def save_patient_test_results(db: Session, patient_id: uuid.UUID, test_id: uuid.UUID,
                              results: list, entered_by: uuid.UUID) -> List[PatientTestResult]:
    """Save result items for a given test in a patient report entry with clinical boundary enforcement."""
    # 1. Validate parameter uniqueness within this submission
    param_ids = [item["parameter_id"] for item in results if "parameter_id" in item]
    if len(param_ids) != len(set(param_ids)):
        raise ValueError(f"Duplicate parameter IDs submitted for test {test_id}")

    # 2. Batch pre-fetch parameters strictly constrained to THIS test_id
    param_map = {}
    if param_ids:
        params = db.query(TestParameter).filter(
            TestParameter.id.in_(param_ids),
            TestParameter.test_id == test_id
        ).all()
        param_map = {p.id: p for p in params}

        # Ensure all submitted parameters actually belong to this test
        if len(params) != len(param_ids):
            missing_ids = set(param_ids) - set(param_map.keys())
            raise ValueError(
                f"Parameter integrity violation: Parameter(s) {missing_ids} do not belong to test {test_id}"
            )

    # 3. Clean previous results for this test atomically before inserting validated set
    db.query(PatientTestResult).filter(
        PatientTestResult.patient_id == patient_id,
        PatientTestResult.test_id == test_id
    ).delete(synchronize_session=False)

    saved_items = []
    for item in results:
        param = param_map.get(item["parameter_id"])
        val_str = str(item.get("entered_value", "")).strip()

        # 4. Authoritative server-side calculation of is_abnormal — never trust client flag
        is_abnormal = calculate_is_abnormal(param, val_str)

        r = PatientTestResult(
            patient_id=patient_id,
            test_id=test_id,
            parameter_id=item["parameter_id"],
            entered_value=val_str,
            is_abnormal=is_abnormal,
            interpretation_note=item.get("interpretation_note"),
            entered_by=entered_by,
        )
        db.add(r)
        saved_items.append(r)

    db.flush()
    return saved_items
