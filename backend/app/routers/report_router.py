"""Report router."""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Form, Query, Body, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
from typing import Optional, Any, List, Dict
import uuid
import os

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, check_patient_access, get_client_ip
from backend.app.services import report_service, audit_service
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/{patient_id}", status_code=201)
def upload_report(
    patient_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    reason: Optional[str] = Form(None),
    force: bool = Query(False),
    partial_release: bool = Query(False),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    filename_lower = file.filename.lower()
    
    # All accepted extensions — images + PDF
    image_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif")
    allowed_extensions = (".pdf",) + image_exts
    
    # Read file bytes synchronously
    file_bytes = file.file.read()

    # Perform multi-layer security validation
    from backend.app.core.upload_security import validate_file_upload
    try:
        sanitized_filename = validate_file_upload(
            file_bytes=file_bytes,
            filename=file.filename,
            max_size=3 * 1024 * 1024,  # 3MB limit for report uploads
            allowed_extensions=allowed_extensions
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    file.filename = sanitized_filename

    # Convert any image format to PDF
    if any(filename_lower.endswith(ext) for ext in image_exts):
        from PIL import Image
        import io
        
        def _convert_to_pdf(f_bytes):
            img = Image.open(io.BytesIO(f_bytes))
            try:
                img.seek(0)
            except (EOFError, AttributeError):
                pass
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            
            # Step 1: Compress to ensure PDF stays under 2.5MB
            max_dim = 1200
            if img.width > max_dim or img.height > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                
            pdf_io = io.BytesIO()
            img.save(pdf_io, format="PDF", resolution=72.0)
            output_bytes = pdf_io.getvalue()
            
            # Step 2: Aggressive compression if it's still > 2.5MB
            if len(output_bytes) > 2.5 * 1024 * 1024:
                img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                pdf_io = io.BytesIO()
                img.save(pdf_io, format="PDF", resolution=72.0)
                output_bytes = pdf_io.getvalue()
                
            return output_bytes

        try:
            file_bytes = _convert_to_pdf(file_bytes)
            base_name = os.path.splitext(file.filename)[0]
            file.filename = f"{base_name}.pdf"
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to convert image to PDF: {str(e)}"
            )

    try:
        return report_service.upload_report(
            db, patient_id, file_bytes, file.filename, current_user.id, background_tasks,
            reason=reason, force=force, partial_release=partial_release
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("DUPLICATE_REPORT:"):
            raise HTTPException(status_code=409, detail=msg.split(":", 1)[1])
        raise HTTPException(status_code=400, detail=msg)



@router.get("/{patient_id}")
def list_reports(patient_id: uuid.UUID, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)
    return report_service.get_patient_reports(db, patient_id)


@router.get("/download/{report_id}")
def download_report(report_id: uuid.UUID,
                    request: Request = None,
                    action: str = Query("view"),
                    current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    from backend.app.models.report import Report
    from backend.app.repositories import patient_repo

    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Enforce patient authorization immediately to prevent IDOR / BOLA
    patient = patient_repo.get_by_id(db, report.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    # Immutable Audit Log: track who (staff/admin), when, and which patient's report was viewed/printed/downloaded
    client_ip = get_client_ip(request) if request else "127.0.0.1"
    log_action = "report.download" if action == "download" else ("report.print" if action == "print" else "report.view")
    audit_service.log(
        db,
        action=log_action,
        actor_user_id=current_user.id,
        entity_type="report",
        entity_id=report.id,
        after={
            "action": action,
            "patient_id": str(patient.id),
            "patient_code": patient.patient_code,
            "patient_name": patient.name,
            "report_id": str(report.id),
            "filename": report.original_filename or "report.pdf",
            "actor_name": getattr(current_user, "name", None),
            "actor_email": getattr(current_user, "email", None),
            "actor_role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        },
        ip_address=client_ip
    )

    from backend.app.config import settings
    from fastapi.responses import Response, FileResponse
    
    disposition = "attachment" if action == "download" else "inline"
    filename = report.original_filename or 'report.pdf'
    
    headers = {
        "Content-Disposition": f"{disposition}; filename=\"{filename}\""
    }

    if report.file_path.startswith("supabase:"):
        parts = report.file_path.replace("supabase:", "").split("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=500, detail="Invalid Supabase storage path")
        bucket_name, file_path_in_bucket = parts
        
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise HTTPException(status_code=500, detail="Supabase configuration missing")
            
        from supabase import create_client, Client
        supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        try:
            res = supabase.storage.from_(bucket_name).download(file_path_in_bucket)
            return Response(content=res, media_type="application/pdf", headers=headers)
        except Exception as e:
            raise HTTPException(status_code=404, detail="Report file not found in Supabase Storage")

    if not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk")

    return FileResponse(report.file_path, media_type="application/pdf", headers=headers)


@router.post("/{report_id}/log-action")
def log_report_action(
    report_id: uuid.UUID,
    request: Request = None,
    payload: Dict[str, Any] = Body(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly audit log a client-side action (e.g. 'print', 'download') on a report."""
    from backend.app.models.report import Report
    from backend.app.repositories import patient_repo

    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    patient = patient_repo.get_by_id(db, report.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    action_type = payload.get("action", "print")
    log_action = f"report.{action_type}"
    client_ip = get_client_ip(request) if request else "127.0.0.1"
    audit_service.log(
        db,
        action=log_action,
        actor_user_id=current_user.id,
        entity_type="report",
        entity_id=report.id,
        after={
            "action": action_type,
            "patient_id": str(patient.id),
            "patient_code": patient.patient_code,
            "patient_name": patient.name,
            "report_id": str(report.id),
            "filename": report.original_filename or "report.pdf",
            "actor_name": getattr(current_user, "name", None),
            "actor_email": getattr(current_user, "email", None),
            "actor_role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        },
        ip_address=client_ip
    )
    return {"status": "ok", "action": log_action}


@router.get("/verify/{report_id}")
def verify_report(report_id: uuid.UUID, h: str = None, db: Session = Depends(get_db)):
    """Public verification endpoint — no auth required."""
    return report_service.verify_report(db, report_id, h)


@router.get("/{patient_id}/test-parameters")
def get_patient_booked_test_parameters(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch all test parameter definitions for tests booked by this patient."""
    from backend.app.repositories import patient_repo, test_parameter_repo
    from backend.app.schemas.test_parameter import TestParameterResponse
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    grouped_params = []
    for pt in patient.patient_tests:
        test_obj = pt.test
        if not test_obj:
            continue
        params = test_parameter_repo.get_by_test_id(db, test_obj.id)
        grouped_params.append({
            "test_id": str(test_obj.id),
            "test_name": test_obj.name,
            "test_code": getattr(test_obj, "test_code", None) or "",
            "parameters": [TestParameterResponse.model_validate(p) for p in params]
        })
    return grouped_params


@router.get("/{patient_id}/test-results")
def get_patient_test_results(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch previously saved structured test results for this patient."""
    from backend.app.repositories import patient_repo, test_parameter_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    results = test_parameter_repo.get_patient_test_results(db, patient_id)
    return [
        {
            "id": str(r.id),
            "patient_id": str(r.patient_id),
            "test_id": str(r.test_id),
            "parameter_id": str(r.parameter_id),
            "entered_value": r.entered_value,
            "is_abnormal": r.is_abnormal,
            "interpretation_note": r.interpretation_note,
            "entered_by": str(r.entered_by),
            "entered_at": r.entered_at.isoformat() if r.entered_at else None,
        }
        for r in results
    ]


@router.post("/{patient_id}/test-attachment/{test_id}")
async def upload_test_attachment(
    patient_id: uuid.UUID,
    test_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an image or PDF attachment (e.g., X-Ray, USG, ECG scan) for a specific test during result entry."""
    from backend.app.repositories import patient_repo
    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    attach_dir = Path("uploads/attachments")
    attach_dir.mkdir(parents=True, exist_ok=True)

    file_bytes = await file.read()
    if len(file_bytes) > 15 * 1024 * 1024:  # 15MB limit
        raise HTTPException(status_code=400, detail="Attachment file size exceeds 15MB limit.")

    from backend.app.core.upload_security import validate_file_upload
    try:
        sanitized_filename = validate_file_upload(
            file_bytes=file_bytes,
            filename=file.filename,
            max_size=15 * 1024 * 1024,
            allowed_extensions=(".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif")
        )
        file.filename = sanitized_filename
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    safe_name = report_service.generate_safe_filename(file.filename, f"{patient.patient_code}_{test_id.hex[:8]}")
    
    from backend.app.config import settings
    if settings.STORAGE_PROVIDER.lower() == "supabase":
        from supabase import create_client, Client
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise HTTPException(status_code=500, detail="Supabase URL or Key is not configured.")
        supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        content_type = file.content_type or "application/octet-stream"
        try:
            supabase.storage.from_("reports").upload(
                path=f"attachments/{safe_name}",
                file=file_bytes,
                file_options={"content-type": content_type}
            )
            db_file_path = f"supabase:reports/attachments/{safe_name}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload attachment to Supabase: {e}")
    else:
        file_path = attach_dir / safe_name
        file_path.write_bytes(file_bytes)
        db_file_path = str(file_path)

    return {
        "status": "success",
        "attachment_path": db_file_path,
        "filename": file.filename
    }


@router.post("/{patient_id}/entry")
def submit_report_entry(
    patient_id: uuid.UUID,
    payload: Any = Body(...),
    partial_release: bool = Query(False),
    background_tasks: BackgroundTasks = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """FR-2.2 (§2.4) — Submit structured test results and queue automated PDF generation."""
    from backend.app.repositories import patient_repo
    from backend.app.services import test_parameter_service
    from backend.app.schemas.report_entry import ReportEntrySubmit

    if background_tasks is None:
        from fastapi import BackgroundTasks
        background_tasks = BackgroundTasks()

    patient = patient_repo.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    # Parse payload
    if isinstance(payload, dict):
        submit_data = ReportEntrySubmit.model_validate(payload)
    else:
        submit_data = payload

    try:
        return test_parameter_service.submit_report_entry(
            db, patient_id, submit_data, current_user.id, background_tasks, partial_release=partial_release, letterhead_mode=submit_data.letterhead_mode
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{report_id}/send-whatsapp")
def send_report_whatsapp(
    report_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Release and deliver the official PDF report to the patient via WhatsApp."""
    from backend.app.models.report import Report
    from backend.app.repositories import patient_repo
    from backend.app.services import notification_service
    from backend.app.config import settings

    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    patient = patient_repo.get_by_id(db, report.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    check_patient_access(current_user, patient)

    if not patient.mobile:
        raise HTTPException(status_code=400, detail="Patient has no registered mobile number")

    file_bytes = None
    # For WhatsApp digital delivery, render official PDF with complete pathology lab header/letterhead
    try:
        from backend.app.services.report_service import generate_patient_report_pdf_bytes
        file_bytes = generate_patient_report_pdf_bytes(db, patient.id, letterhead_mode=True)
    except Exception as e:
        import logging
        logging.getLogger("akriti.reports").warning(f"On-the-fly letterhead PDF generation skipped/failed ({e}), falling back to stored report.")

    if not file_bytes:
        if report.file_path.startswith("supabase:"):
            parts = report.file_path.replace("supabase:", "").split("/", 1)
            if len(parts) == 2:
                bucket_name, file_path_in_bucket = parts
                from supabase import create_client
                supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
                try:
                    file_bytes = supabase.storage.from_(bucket_name).download(file_path_in_bucket)
                except Exception as e:
                    raise HTTPException(status_code=404, detail=f"Report file not found in Supabase: {e}")
        else:
            if not os.path.exists(report.file_path):
                raise HTTPException(status_code=404, detail="Report file not found on disk")
            with open(report.file_path, "rb") as f:
                file_bytes = f.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Unable to retrieve report document bytes")

    filename = report.original_filename or f"Report_{patient.patient_code}.pdf"

    background_tasks.add_task(
        notification_service.notify,
        "report_released",
        patient.mobile,
        {
            "patient_name": patient.name,
            "patient_code": patient.patient_code,
            "attachment_bytes": file_bytes,
            "attachment_name": filename,
            "mobile": patient.mobile,
        }
    )

    audit_service.log(
        db,
        action="report.release_whatsapp",
        actor_user_id=current_user.id,
        entity_type="report",
        entity_id=report.id,
        after={
            "patient_id": str(patient.id),
            "patient_code": patient.patient_code,
            "mobile": patient.mobile,
            "report_id": str(report.id),
            "filename": filename
        }
    )
    db.commit()

    return {
        "success": True,
        "message": f"Report PDF dispatched to patient WhatsApp (+91 {patient.mobile}) successfully."
    }

