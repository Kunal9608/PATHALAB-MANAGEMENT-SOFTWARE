"""
FastAPI application — wires all routers, middleware, static file serving.
This file does NOT contain business logic — only app assembly.
"""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from backend.app.core.limiter import limiter

from backend.app.config import settings
from backend.app.dependencies import require_admin
from backend.app.middleware.error_handler import (
    validation_exception_handler,
    value_error_handler,
    permission_error_handler,
    generic_exception_handler,
)
from backend.app.routers import (
    auth_router, staff_router, attendance_router,
    patient_router, test_router, report_router,
    finance_router, security_router, copilot_router,
)
from backend.app.core.db import init_db, get_db
from sqlalchemy.orm import Session

ROOT = Path(__file__).parent.parent.parent  # project root
FRONTEND_DIR = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize DB tables if they don't exist (fallback for no Alembic)."""
    if settings.is_production:
        if settings.JWT_SECRET_KEY == "change-this-secret":
            import sys
            print("  [FATAL] JWT_SECRET_KEY is using the default insecure value in production. Exiting.")
            sys.exit(1)
            
    try:
        init_db()
    except Exception as e:
        print(f"  [WARN] DB init: {e}")
        if settings.is_production:
            import sys
            print("  [FATAL] Database initialization failed in production. Exiting to prevent silent failures.")
            sys.exit(1)
    yield


# Disable Swagger UI and ReDoc in production to prevent API schema exposure
_docs_url = None if os.getenv("ENVIRONMENT", "development").lower() == "production" else "/docs"
_redoc_url = None if os.getenv("ENVIRONMENT", "development").lower() == "production" else "/redoc"

app = FastAPI(
    title="Akriti Diagnostics Center — Lab Management System",
    description="Pathology lab management API",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later.", "message": "Rate limit exceeded"}
    )

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Clean URLs Middleware ────────────────────────────────────────────────────
@app.middleware("http")
async def clean_urls_middleware(request: Request, call_next):
    path = request.url.path
    
    # If path starts with API prefix or health or static paths with dots, bypass
    if path.startswith("/api/") or path == "/health" or path.startswith("/docs") or path.startswith("/redoc"):
        return await call_next(request)
        
    # Check if request is for a clean HTML path (e.g. /admin/dashboard)
    last_segment = path.split("/")[-1]
    if not path.endswith("/") and "." not in last_segment:
        rel_path = path.lstrip("/")
        file_path = FRONTEND_DIR / f"{rel_path}.html"
        if file_path.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(str(file_path), media_type="text/html")
            
    # If path ends in .html directly, redirect to clean URL
    if path.endswith(".html"):
        clean_path = path[:-5]
        if clean_path.endswith("/index"):
            clean_path = clean_path[:-5] or "/"
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=clean_path, status_code=301)
        
    return await call_next(request)


# ── Web Security Headers Middleware ──────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    
    # 1. Content Security Policy (CSP)
    # Allows self, Google Fonts, flatpickr, ChartJS, cloudflare QRcode.js, and Google reCAPTCHA
    csp_directives = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://www.google.com/recaptcha/ https://www.gstatic.com/recaptcha/; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https://api.qrserver.com; "
        "connect-src 'self' https://www.google.com/recaptcha/; "
        "frame-src 'self' https://www.google.com/recaptcha/ https://recaptcha.google.com/recaptcha/; "
        "frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy"] = csp_directives
    
    # 2. Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    
    # 3. Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # 4. Cross-Site Scripting protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # 5. Referrer Policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # 6. HTTP Strict Transport Security (HSTS) - only in production
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    
    # 7. Permissions Policy — disable sensitive browser APIs not needed by the app
    response.headers["Permissions-Policy"] = (
        "accelerometer=(), "
        "camera=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "payment=(), "
        "usb=()"
    )
    
    # 8. Remove server fingerprinting header
    if "server" in response.headers:
        del response.headers["server"]
        
    return response


# ── Exception handlers ────────────────────────────────────────────────────────
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(PermissionError, permission_error_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── API routers ───────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"
app.include_router(auth_router.router, prefix=API_PREFIX)
app.include_router(staff_router.router, prefix=API_PREFIX)
app.include_router(attendance_router.router, prefix=API_PREFIX)
app.include_router(patient_router.router, prefix=API_PREFIX)
app.include_router(test_router.router, prefix=API_PREFIX)
app.include_router(report_router.router, prefix=API_PREFIX)
app.include_router(finance_router.router, prefix=API_PREFIX)
app.include_router(security_router.router, prefix=API_PREFIX)
app.include_router(copilot_router.router, prefix=API_PREFIX)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health(db: Session = Depends(get_db)):
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "Akriti Lab Management System", "database": "connected"}
    except Exception as e:
        # Never expose internal DB error details to the outside world
        detail = str(e) if not settings.is_production else "Database unreachable"
        return JSONResponse(
            status_code=503,
            content={"status": "error", "service": "Akriti Lab Management System", "database": "disconnected", "detail": detail}
        )


# ── Exception Handlers ────────────────────────────────────────────────────────
import logging
from sqlalchemy.exc import OperationalError, InterfaceError

logger = logging.getLogger("app")

@app.exception_handler(OperationalError)
async def db_operational_exception_handler(request: Request, exc: OperationalError):
    logger.error(f"Database operational error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is temporarily unreachable. Please try again in a few seconds."}
    )

@app.exception_handler(InterfaceError)
async def db_interface_exception_handler(request: Request, exc: InterfaceError):
    logger.error(f"Database interface error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database connection interface error. Please try again in a few seconds."}
    )


# ── Settings API (lab config) ─────────────────────────────────────────────────
# In-memory overlay for lab settings (persists for process lifetime)
_lab_settings_overlay: dict = {}


@app.get("/api/v1/settings/lab")
def get_lab_settings(current_user=Depends(require_admin)):
    """Admin-only: returns lab configuration including reCAPTCHA and notification state."""
    from backend.app.services import notification_service
    return {
        "lab_name":     _lab_settings_overlay.get("lab_name",     settings.LAB_NAME),
        "lab_upi_vpa":  _lab_settings_overlay.get("lab_upi_vpa",  settings.LAB_UPI_VPA),
        "lab_phone":    _lab_settings_overlay.get("lab_phone",    settings.LAB_PHONE),
        "lab_address":  _lab_settings_overlay.get("lab_address",  settings.LAB_ADDRESS),
        "lab_gstin":    _lab_settings_overlay.get("lab_gstin",    settings.LAB_GSTIN),
        "report_footer": _lab_settings_overlay.get("report_footer", ""),
        "email_notifications_enabled": notification_service.EMAIL_NOTIFICATIONS_ENABLED,
        "recaptcha_site_key": settings.RECAPTCHA_SITE_KEY,
        "recaptcha_enabled": settings.ENABLE_RECAPTCHA,
    }


@app.get("/api/v1/settings/lab/public")
def get_lab_settings_public():
    """Public endpoint: returns only the minimal info needed for the login page (reCAPTCHA)."""
    return {
        "recaptcha_site_key": settings.RECAPTCHA_SITE_KEY,
        "recaptcha_enabled": settings.ENABLE_RECAPTCHA,
        "lab_name": _lab_settings_overlay.get("lab_name", settings.LAB_NAME),
    }


from pydantic import BaseModel as PydanticBaseModel


class LabSettingsPatchSchema(PydanticBaseModel):
    lab_name: Optional[str] = None
    lab_address: Optional[str] = None
    lab_phone: Optional[str] = None
    lab_upi_vpa: Optional[str] = None
    lab_gstin: Optional[str] = None
    report_footer: Optional[str] = None
    email_notifications_enabled: Optional[bool] = None


@app.patch("/api/v1/settings/lab")
def patch_lab_settings(
    payload: LabSettingsPatchSchema,
    current_user=Depends(require_admin),
):
    global _lab_settings_overlay
    update = payload.model_dump(exclude_none=True)
    if "email_notifications_enabled" in update:
        from backend.app.services import notification_service
        notification_service.EMAIL_NOTIFICATIONS_ENABLED = update["email_notifications_enabled"]
    _lab_settings_overlay.update(update)
    return get_lab_settings()


class DeleteOtpRequestSchema(PydanticBaseModel):
    password: str


@app.post("/api/v1/settings/delete-request-otp")
def delete_request_otp(
    payload: DeleteOtpRequestSchema,
    request: Request,
    current_user=Depends(require_admin),
):
    from backend.app.core.db import SessionLocal
    from backend.app.core.security import verify_password
    from backend.app.services import auth_service
    from fastapi import HTTPException
    
    is_valid, _ = verify_password(payload.password, current_user.password_hash)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Incorrect account password")
        
    db = SessionLocal()
    try:
        ip = request.client.host if request.client else "0.0.0.0"
        auth_service.request_otp(db, current_user.email, "delete_verify", ip)
    finally:
        db.close()
    return {"message": "OTP has been sent to your registered email address"}


class DeleteEverythingSchema(PydanticBaseModel):
    password: str
    otp: str


@app.post("/api/v1/settings/delete-everything")
def delete_everything(
    payload: DeleteEverythingSchema,
    request: Request,
    current_user=Depends(require_admin),
):
    from backend.app.core.db import SessionLocal
    from backend.app.core.security import verify_password
    from backend.app.services import auth_service, pdf_generator
    from fastapi.responses import StreamingResponse
    from fastapi import HTTPException
    import io
    
    # 1. Verify Password
    is_valid, _ = verify_password(payload.password, current_user.password_hash)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Incorrect account password")
        
    db = SessionLocal()
    try:
        # 2. Verify OTP
        ip = request.client.host if request.client else "0.0.0.0"
        ua = request.headers.get("user-agent")
        try:
            auth_service.verify_otp_code(db, current_user.email, payload.otp, "delete_verify", ip, ua)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 3. Query patients from past 15 days
        from backend.app.models.patient import Patient
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import and_
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=15)
        patients = db.query(Patient).filter(
            and_(
                Patient.created_at >= cutoff,
                Patient.deleted_at.is_(None)
            )
        ).order_by(Patient.created_at.desc()).limit(50).all()
        
        # 4. Generate backup PDF
        try:
            pdf_bytes = pdf_generator.generate_patients_pdf(patients)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate backup PDF: {str(e)}")

        # 5. Clean report files from disk
        import glob
        import os
        for f in glob.glob("uploads/reports/*"):
            try:
                os.remove(f)
            except Exception:
                pass

        # 6. Hard delete patient-related data ONLY for the identified patients
        from backend.app.models.patient_test import PatientTest
        from backend.app.models.report import Report

        if patients:
            patient_ids = [p.id for p in patients]
            db.query(Report).filter(Report.patient_id.in_(patient_ids)).delete(synchronize_session=False)
            db.query(PatientTest).filter(PatientTest.patient_id.in_(patient_ids)).delete(synchronize_session=False)
            db.query(Patient).filter(Patient.id.in_(patient_ids)).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Database wipe failed: {e}")
    finally:
        db.close()

    # Return PDF as attachment download
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=patient_backup_15days.pdf"}
    )


# ── Static frontend (served at /) ─────────────────────────────────────────────
if FRONTEND_DIR.exists():
    # Serve specific subdirectories
    for sub in ["assets", "admin", "staff"]:
        sub_dir = FRONTEND_DIR / sub
        if sub_dir.exists():
            app.mount(f"/{sub}", StaticFiles(directory=str(sub_dir)), name=sub)

    # Serve root-level HTML pages and service worker
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "Frontend not built yet. API is running at /api/v1/"}
