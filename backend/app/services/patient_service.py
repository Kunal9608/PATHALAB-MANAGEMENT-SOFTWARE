"""Patient service — Patient ID generation, create/update, payment logic."""
from datetime import date, datetime, timezone, timedelta
from typing import Optional, List
import uuid

from sqlalchemy.orm import Session

from backend.app.repositories import patient_repo, test_repo
from backend.app.services import audit_service
from backend.app.schemas.patient import PatientCreate, PatientUpdate
from backend.app.models.patient import PatientStatusEnum

def _check_duplicates(db: Session, mobile: str, sample_date: date, test_ids: List[uuid.UUID], exclude_patient_id: Optional[uuid.UUID] = None, force_duplicate: bool = False):
    from backend.app.models.patient import Patient
    from backend.app.models.patient_test import PatientTest
    from backend.app.models.test import Test
    from fastapi import HTTPException
    
    # 1. Real-time duplicate detection: same mobile within 24 hours
    if not force_duplicate:
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_query = db.query(Patient).filter(
            Patient.mobile == mobile,
            Patient.created_at >= time_threshold,
            Patient.deleted_at.is_(None)
        )
        if exclude_patient_id:
            recent_query = recent_query.filter(Patient.id != exclude_patient_id)
            
        recent_patient = recent_query.order_by(Patient.created_at.desc()).first()
        if recent_patient:
            existing_info = {
                "id": str(recent_patient.id),
                "name": recent_patient.name,
                "mobile": recent_patient.mobile,
                "created_at": recent_patient.created_at.isoformat() if recent_patient.created_at else None
            }
            raise HTTPException(
                status_code=409,
                detail={"message": "Possible duplicate patient detected.", "existing_patient": existing_info}
            )

    # 2. Existing check: same day, same tests
    query = db.query(Patient).filter(
        Patient.mobile == mobile,
        Patient.sample_date == sample_date,
        Patient.deleted_at.is_(None)
    )
    if exclude_patient_id:
        query = query.filter(Patient.id != exclude_patient_id)

    existing_patients = query.all()
    if existing_patients:
        existing_patient_ids = [p.id for p in existing_patients]
        duplicates = db.query(PatientTest).filter(
            PatientTest.patient_id.in_(existing_patient_ids),
            PatientTest.test_id.in_(test_ids)
        ).all()
        if duplicates:
            dup_test_ids = [d.test_id for d in duplicates]
            dup_tests = db.query(Test).filter(Test.id.in_(dup_test_ids)).all()
            dup_names = ", ".join([str(t.name) for t in dup_tests])
            raise ValueError(f"Patient with mobile {mobile} has already booked test(s) ({dup_names}) on this day")


def create_patient(db: Session, payload: PatientCreate, current_user_id: uuid.UUID,
                   background_tasks, idempotency_key: Optional[str] = None) -> dict:
    """FR-4.1, FR-4.2 — Create patient with sequence-based ID generation."""
    year = date.today().year

    # Generate Patient ID using PostgreSQL sequence (never MAX+1)
    patient_code = patient_repo.generate_patient_code(db, year)

    # Server-recompute total from current test prices — never trust client total
    price_map = test_repo.get_current_prices(db, payload.test_ids)
    if len(price_map) != len(payload.test_ids):
        missing = [str(tid) for tid in payload.test_ids if str(tid) not in price_map]
        raise ValueError(f"Tests not found: {missing}")

    # Check same-day same-test duplicates for the patient (by contact number)
    sample_date = payload.sample_date or date.today()
    _check_duplicates(db, payload.mobile, sample_date, payload.test_ids, force_duplicate=payload.force_duplicate)

    from decimal import Decimal

    total_amount = Decimal(sum(price_map.values()))
    amount_paid = Decimal(str(payload.amount_paid or 0))
    discount_amount = Decimal(str(payload.discount_amount or 0))

    if discount_amount < 0:
        raise ValueError("Discount amount cannot be negative")
    if discount_amount > total_amount:
        raise ValueError("Discount cannot exceed total amount")

    effective_total = total_amount - discount_amount
    if amount_paid > effective_total:
        raise ValueError("Amount paid cannot exceed total after discount")

    sample_date = payload.sample_date or date.today()
    if sample_date > date.today():
        raise ValueError("sample_date cannot be in the future")

    estimated_report_date = payload.estimated_report_date or (sample_date + timedelta(days=1))

    commission_pct = Decimal(0)
    commission_amount = Decimal(0)
    if payload.doctor_id:
        from backend.app.models.doctor import Doctor
        doc = db.query(Doctor).filter(Doctor.id == payload.doctor_id).first()
        if doc:
            commission_pct = Decimal(str(doc.commission_pct))
            commission_amount = round(effective_total * (commission_pct / Decimal(100)), 2)

    patient = patient_repo.create_patient(
        db,
        patient_code=patient_code,
        name=payload.name,
        age=payload.age,
        gender=payload.gender,
        mobile=payload.mobile,
        doctor_id=payload.doctor_id,
        collected_by=current_user_id,
        collection_type=payload.collection_type,
        sample_date=sample_date,
        estimated_report_date=estimated_report_date,
        total_amount=float(total_amount),
        discount_amount=float(discount_amount),
        amount_paid=float(amount_paid),
        payment_mode=payload.payment_mode if amount_paid > 0 else None,
        referred_doctor_commission_pct=float(commission_pct),
        referred_doctor_commission_amount=float(commission_amount),
    )

    # Insert patient_tests with price snapshot
    for test_id in payload.test_ids:
        patient_repo.add_patient_test(db, patient.id, test_id, price_map[str(test_id)])

    from backend.app.models.patient_status_history import PatientStatusHistory
    initial_history = PatientStatusHistory(
        patient_id=patient.id,
        status="sample_collected",
        updated_by=current_user_id,
    )
    db.add(initial_history)

    audit_service.log(
        db, "patient.create",
        actor_user_id=current_user_id,
        entity_type="patient",
        entity_id=patient.id,
        after={"patient_code": patient_code, "name": payload.name, "total": total_amount},
    )

    from backend.app.services import notification_service
    background_tasks.add_task(
        notification_service.notify,
        "patient_registered",
        patient.mobile,
        {
            "patient_name": patient.name,
            "patient_code": patient_code,
        }
    )

    db.commit()
    try:
        from backend.app.core import copilot_cache
        copilot_cache.invalidate_patient_sync(patient_code)
    except Exception:
        pass
    return _patient_to_dict(db, patient)


def update_patient(db: Session, patient_id: uuid.UUID, payload: PatientUpdate,
                   current_user_id: uuid.UUID, background_tasks = None) -> dict:
    """FR-4.1 — Edit patient. Recomputes total if tests changed."""
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")

    before = _patient_to_dict(db, patient)
    update_data = payload.model_dump(exclude_none=True)

    new_mobile = payload.mobile or patient.mobile
    new_sample_date = payload.sample_date or patient.sample_date
    new_test_ids = payload.test_ids if payload.test_ids is not None else [t.test_id for t in (patient.patient_tests or [])]

    if payload.mobile is not None or payload.sample_date is not None or payload.test_ids is not None:
        _check_duplicates(db, new_mobile, new_sample_date, new_test_ids, exclude_patient_id=patient.id, force_duplicate=payload.force_duplicate)

    # Remove force_duplicate from update_data so it doesn't try to save it to DB
    if "force_duplicate" in update_data:
        update_data.pop("force_duplicate")

    # If tests changed, recompute total
    from decimal import Decimal
    
    if "test_ids" in update_data:
        price_map = test_repo.get_current_prices(db, update_data["test_ids"])
        total_amount = Decimal(sum(price_map.values()))
        patient_repo.delete_patient_tests(db, patient_id)
        for test_id in update_data.pop("test_ids"):
            patient_repo.add_patient_test(db, patient_id, test_id, price_map[str(test_id)])
        update_data["total_amount"] = float(total_amount)

    # Validate payment
    discount_amount = Decimal(str(update_data.get("discount_amount", patient.discount_amount or 0)))
    amount_paid = Decimal(str(update_data.get("amount_paid", patient.amount_paid or 0)))
    total = Decimal(str(update_data.get("total_amount", patient.total_amount or 0)))
    if discount_amount < 0:
        raise ValueError("Discount amount cannot be negative")
    if discount_amount > total:
        raise ValueError("Discount cannot exceed total amount")
    if amount_paid > (total - discount_amount):
        raise ValueError("Amount paid cannot exceed total after discount")

    # Recompute doctor commission if doctor_id, total_amount, or discount_amount changed
    if "doctor_id" in update_data or "total_amount" in update_data or "discount_amount" in update_data:
        new_doc_id = update_data.get("doctor_id") if "doctor_id" in update_data else patient.doctor_id
        new_total = update_data.get("total_amount") if "total_amount" in update_data else patient.total_amount
        new_discount = update_data.get("discount_amount") if "discount_amount" in update_data else patient.discount_amount
        
        commission_pct = Decimal(0)
        commission_amount = Decimal(0)
        if new_doc_id:
            from backend.app.models.doctor import Doctor
            doc = db.query(Doctor).filter(Doctor.id == new_doc_id).first()
            if doc:
                commission_pct = Decimal(str(doc.commission_pct))
                effective_total = Decimal(str(new_total or 0)) - Decimal(str(new_discount or 0))
                commission_amount = round(effective_total * (commission_pct / Decimal(100)), 2)
        
        update_data["referred_doctor_commission_pct"] = float(commission_pct)
        update_data["referred_doctor_commission_amount"] = float(commission_amount)

    new_status = update_data.get("status")
    if new_status and new_status != patient.status:
        if patient.status == PatientStatusEnum.report_ready or str(patient.status) == "report_ready":
            raise ValueError("Status cannot be modified once the report is released (report_ready).")
        extra_info = {}
        if new_status == "sent_to_franchise":
            extra_info = {
                "franchise_name": update_data.get("franchise_name", patient.franchise_name),
                "franchise_other": update_data.get("franchise_other", patient.franchise_other),
                "sample_sent_date": str(update_data.get("sample_sent_date", patient.sample_sent_date)) if update_data.get("sample_sent_date", patient.sample_sent_date) else None,
                "sample_sent_time": update_data.get("sample_sent_time", patient.sample_sent_time),
                "courier_name": update_data.get("courier_name", patient.courier_name),
                "tracking_id": update_data.get("tracking_id", patient.tracking_id),
                "remarks": update_data.get("franchise_remarks", patient.franchise_remarks),
            }
        from backend.app.models.patient_status_history import PatientStatusHistory
        status_history_entry = PatientStatusHistory(
            patient_id=patient_id,
            status=new_status,
            updated_by=current_user_id,
            extra_info=extra_info
        )
        db.add(status_history_entry)

        from backend.app.services import notification_service
        if background_tasks and new_status not in ["report_ready", "partial_release"]:
            background_tasks.add_task(
                notification_service.notify,
                "status_update",
                patient.mobile,
                {
                    "patient_name": patient.name,
                    "patient_code": patient.patient_code,
                    "status": new_status,
                }
            )

    patient_repo.update_patient(db, patient_id, **update_data)
    audit_service.log(
        db, "patient.edit",
        actor_user_id=current_user_id,
        entity_type="patient",
        entity_id=patient_id,
        before=before,
        after=update_data,
    )
    db.commit()

    patient = patient_repo.get_by_id(db, patient_id)
    if patient and patient.patient_code:
        try:
            from backend.app.core import copilot_cache
            copilot_cache.invalidate_patient_sync(str(patient.patient_code))
        except Exception:
            pass
    return _patient_to_dict(db, patient, include_history=True)


def get_patient(db: Session, patient_id: uuid.UUID) -> dict:
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")
    return _patient_to_dict(db, patient, include_history=True)


def list_patients(db: Session, current_user, **kwargs) -> dict:
    """FR-6.1 — view_scope enforcement happens here in the service."""
    from backend.app.models.user import RoleEnum, ViewScopeEnum

    # Server-side scope enforcement — cannot be bypassed
    if current_user.role == RoleEnum.staff and current_user.view_scope == ViewScopeEnum.own:
        kwargs["collected_by"] = current_user.id

    page = kwargs.pop("page", 1)
    page_size = min(kwargs.pop("page_size", 20), 100)
    if kwargs.get("q"):
        page_size = 3

    items, total = patient_repo.list_patients(db, page=page, page_size=page_size, **kwargs)
    total_pages = (total + page_size - 1) // page_size

    return {
        "items": [_patient_to_dict(db, p) for p in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def export_patients_csv(db: Session, date_from: Optional[date], date_to: Optional[date]):
    from fastapi.responses import StreamingResponse
    import io
    import csv
    from sqlalchemy import or_, and_
    from backend.app.models.patient import Patient

    query = db.query(Patient).filter(Patient.deleted_at.is_(None))
    if date_from and date_to:
        start_dt = datetime.combine(date_from, datetime.min.time())
        end_dt = datetime.combine(date_to, datetime.max.time())
        query = query.filter(
            or_(
                and_(Patient.sample_date >= date_from, Patient.sample_date <= date_to),
                and_(Patient.created_at >= start_dt, Patient.created_at <= end_dt)
            )
        )
        query = query.order_by(Patient.created_at.desc())
    else:
        query = query.order_by(Patient.created_at.desc()).limit(20)

    def iter_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Patient ID', 'Name', 'Date', 'Total Bill', 'Discount', 'Net Paid', 'Due', 'Status', 'Payment Mode'])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # yield_per prevents loading all rows into memory simultaneously
        for p in query.yield_per(1000):
            disc = float(p.discount_amount or 0)
            net_paid = float(p.amount_paid or 0)
            due = float(p.amount_due or 0)
            date_val = p.sample_date or (p.created_at.date() if p.created_at else None)
            date_str = date_val.strftime('%Y-%m-%d') if date_val else ''
            
            writer.writerow([
                p.patient_code or '',
                p.name or '',
                date_str,
                float(p.total_amount or 0),
                disc,
                net_paid,
                due,
                p.status.value if hasattr(p.status, 'value') else str(p.status) if p.status else '',
                p.payment_mode or ''
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"patients_{date_from or 'all'}_to_{date_to or 'all'}.csv"
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(iter_csv(), media_type="text/csv", headers=headers)


def generate_qr_payload(db: Session, patient_id: uuid.UUID) -> str:
    """FR-4.3 — local UPI deep-link, no external API."""
    from backend.app.config import settings
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise ValueError("Patient not found")

    due = float(patient.total_amount or 0) - float(patient.amount_paid or 0)
    if due <= 0:
        due = float(patient.total_amount or 0)

    vpa = settings.LAB_UPI_VPA
    lab_name = settings.LAB_NAME.replace(" ", "%20")
    return (
        f"upi://pay?pa={vpa}&pn={lab_name}"
        f"&am={due:.2f}&cu=INR&tn={patient.patient_code}"
    )


def _patient_to_dict(db: Session, patient, include_history: bool = False) -> dict:
    """Convert Patient ORM object to dict for API response."""
    tests = []
    for pt in (patient.patient_tests or []):
        test_obj = pt.test
        price = float(pt.price_at_booking)
        tests.append({
            "id": str(pt.test_id),           # test UUID
            "test_id": str(pt.test_id),      # alias used by setSelectedTests()
            "name": test_obj.name if test_obj else "Unknown",
            "price": price,                  # alias expected by frontend
            "price_at_booking": price,       # kept for schema compatibility
        })

    status_str = patient.status.value if hasattr(patient.status, 'value') else str(patient.status)
    report_released_at = None
    if status_str == "report_ready" and patient.reports:
        latest_report = max(patient.reports, key=lambda r: r.uploaded_at)
        if latest_report.uploaded_at:
            report_released_at = latest_report.uploaded_at.isoformat()

    history_list = None
    if include_history:
        histories = patient.status_history or []
        history_list = []
        for h in histories:
            history_list.append({
                "id": str(h.id),
                "status": h.status,
                "updated_at": h.updated_at.isoformat(),
                "updater_name": h.updater.name if h.updater else "Unknown",
                "updater_role": h.updater.role.value if h.updater and hasattr(h.updater.role, 'value') else str(h.updater.role) if h.updater else "Unknown",
                "extra_info": h.extra_info,
            })

    return {
        "id": str(patient.id),
        "patient_code": patient.patient_code,
        "name": patient.name,
        "age": patient.age,
        "gender": patient.gender,
        "mobile": patient.mobile,
        "doctor_id": str(patient.doctor_id) if patient.doctor_id else None,
        "doctor_name": patient.doctor.name if patient.doctor else None,
        "collection_type": patient.collection_type,
        "sample_date": str(patient.sample_date) if patient.sample_date else None,
        "estimated_report_date": str(patient.estimated_report_date),
        "report_released_at": report_released_at,
        "total_amount": float(patient.total_amount or 0),
        "discount_amount": float(patient.discount_amount or 0),
        "amount_paid": float(patient.amount_paid or 0),
        "amount_due": float(patient.amount_due or 0),
        "payment_mode": patient.payment_mode,
        "payment_status": patient.payment_status,
        "referred_doctor_commission_pct": float(patient.referred_doctor_commission_pct or 0.0),
        "referred_doctor_commission_amount": float(patient.referred_doctor_commission_amount or 0.0),
        "status": patient.status.value if hasattr(patient.status, 'value') else str(patient.status),
        "processing_note": patient.processing_note,
        "created_at": patient.created_at.isoformat() if patient.created_at else None,
        "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
        "tests": tests,
        "collected_by_name": patient.collector.name if patient.collector else None,
        
        # Franchise Fields
        "franchise_name": patient.franchise_name,
        "franchise_other": patient.franchise_other,
        "sample_sent_date": str(patient.sample_sent_date) if patient.sample_sent_date else None,
        "sample_sent_time": patient.sample_sent_time,
        "courier_name": patient.courier_name,
        "tracking_id": patient.tracking_id,
        "franchise_remarks": patient.franchise_remarks,
        "status_history": history_list,
    }
