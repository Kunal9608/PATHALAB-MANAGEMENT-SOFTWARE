"""
PathLab OS — WhatsApp Router
Handles Admin-controlled WhatsApp connection lifecycle (QR scan, status, disconnect),
and Patient WhatsApp OTP delivery & verification.
"""
import secrets
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.config import settings
from backend.app.dependencies import require_admin, get_current_user
from backend.app.models.user import User
from backend.app.models.otp_request import OtpRequest, OtpPurposeEnum
from backend.app.services.whatsapp_service import whatsapp_service
from backend.app.services import audit_service
from backend.app.core.redis_client import get_redis

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# In-memory rate limiting and attempts tracking fallbacks
_otp_mobile_attempts = {}
_otp_mobile_cooldown = {}


# ── Schemas ──────────────────────────────────────────────────────────────────

class TestMessageRequest(BaseModel):
    to: str
    message: Optional[str] = "Hello! This is a test message from Akriti Diagnostics Center WhatsApp service."

    @field_validator("to")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        clean = "".join(filter(str.isdigit, str(v)))
        if len(clean) < 10 or len(clean) > 13:
            raise ValueError("Recipient phone number must be 10-12 digits")
        return clean


class WhatsAppOtpRequest(BaseModel):
    mobile: str
    name: Optional[str] = "Patient"

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        clean = "".join(filter(str.isdigit, str(v)))
        if len(clean) == 10:
            return clean
        if len(clean) == 12 and clean.startswith("91"):
            return clean[2:]
        raise ValueError("Mobile number must be a valid 10-digit Indian number")


class WhatsAppOtpVerify(BaseModel):
    mobile: str
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 6:
            raise ValueError("OTP must be a 6-digit numeric code")
        return v


# ── Helper OTP Cryptographic Functions ───────────────────────────────────────

def _generate_secure_otp() -> str:
    """Generate a 6-digit cryptographically secure numeric OTP using secrets."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(otp: str, mobile: str) -> str:
    """Generate HMAC-SHA256 hash using server-side secret key bound to phone number."""
    key = settings.JWT_SECRET_KEY.encode("utf-8")
    msg = f"{mobile}:{otp}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


# ── Admin WhatsApp Connection Endpoints ─────────────────────────────────────

@router.get("/status")
def get_whatsapp_status(admin: User = Depends(require_admin)):
    """Admin only: Check WhatsApp service and connection status."""
    return whatsapp_service.get_status()


@router.post("/connect")
def connect_whatsapp(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin only: Trigger WhatsApp multi-device connection & QR code generation."""
    result = whatsapp_service.connect()
    audit_service.log(
        db,
        "whatsapp.connect_requested",
        actor_user_id=admin.id,
        entity_type="whatsapp",
        after={"status": result.get("status")}
    )
    db.commit()
    return result


@router.get("/qr")
def get_whatsapp_qr(admin: User = Depends(require_admin)):
    """Admin only: Retrieve active QR code data URL for scanning."""
    return whatsapp_service.get_qr()


@router.post("/disconnect")
def disconnect_whatsapp(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin only: Disconnect WhatsApp session and log out."""
    result = whatsapp_service.disconnect()
    audit_service.log(
        db,
        "whatsapp.disconnected",
        actor_user_id=admin.id,
        entity_type="whatsapp",
        after={"success": result.get("success")}
    )
    db.commit()
    return result


@router.post("/test-message")
def send_test_message(payload: TestMessageRequest, admin: User = Depends(require_admin)):
    """Admin only: Send a test WhatsApp message to verify channel health."""
    status_info = whatsapp_service.get_status()
    if not status_info.get("connected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp is not connected. Please scan QR code in Settings first."
        )

    ok = whatsapp_service.send_text(payload.to, payload.message)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send test message. Check service logs."
        )

    return {"success": True, "message": f"Test message dispatched to +{payload.to}"}


# ── Patient WhatsApp OTP Endpoints ──────────────────────────────────────────

@router.post("/otp/request")
def request_whatsapp_otp(payload: WhatsAppOtpRequest, request: Request, db: Session = Depends(get_db)):
    """
    Request a 6-digit WhatsApp OTP for patient registration/verification.
    Applies cooldown, rate-limiting, and server-side HMAC hashing.
    """
    status_info = whatsapp_service.get_status()
    if not status_info.get("connected"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp verification is currently unavailable. Please ask lab staff for manual registration."
        )

    mobile = payload.mobile
    ip = request.client.host if request.client else "0.0.0.0"
    r = get_redis()
    now_ts = datetime.now(timezone.utc).timestamp()

    # 1. Check Cooldown (60s default)
    cooldown_key = f"wa_otp_cd:{mobile}"
    if r:
        if r.exists(cooldown_key):
            ttl = r.ttl(cooldown_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {ttl} seconds before requesting another OTP."
            )
    else:
        last_req = _otp_mobile_cooldown.get(mobile, 0)
        if now_ts - last_req < settings.WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS:
            rem = int(settings.WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS - (now_ts - last_req))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {rem} seconds before requesting another OTP."
            )

    # 2. Generate secure 6-digit OTP
    otp_code = _generate_secure_otp()
    otp_hash = _hash_otp(otp_code, mobile)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.WHATSAPP_OTP_EXPIRY_SECONDS)

    # 3. Store OTP record bound to phone number
    otp_record = OtpRequest(
        email=f"wa:{mobile}",  # Prefix with wa: to store safely in existing OtpRequest schema
        otp_hash=otp_hash,
        purpose=OtpPurposeEnum.login,
        expires_at=expires,
        requesting_ip=ip
    )
    db.add(otp_record)
    db.commit()

    # 4. Dispatch via WhatsApp
    sent = whatsapp_service.send_otp(mobile, otp_code, name=payload.name)
    if not sent:
        db.delete(otp_record)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deliver WhatsApp message. Please check the mobile number and try again."
        )

    # 5. Set Cooldown & Reset attempts
    if r:
        r.setex(cooldown_key, settings.WHATSAPP_OTP_RESEND_COOLDOWN_SECONDS, "1")
        r.delete(f"wa_otp_attempts:{mobile}")
    else:
        _otp_mobile_cooldown[mobile] = now_ts
        _otp_mobile_attempts[mobile] = 0

    return {
        "success": True,
        "message": "OTP has been sent to your WhatsApp number.",
        "expires_in_seconds": settings.WHATSAPP_OTP_EXPIRY_SECONDS
    }


@router.post("/otp/verify")
def verify_whatsapp_otp(payload: WhatsAppOtpVerify, db: Session = Depends(get_db)):
    """
    Verify 6-digit WhatsApp OTP.
    Enforces expiry, single-use, and max 3 incorrect attempts.
    """
    mobile = "".join(filter(str.isdigit, str(payload.mobile)))
    otp_code = payload.otp
    r = get_redis()

    # Check attempt limit
    attempts_key = f"wa_otp_attempts:{mobile}"
    if r:
        attempts = int(r.get(attempts_key) or 0)
    else:
        attempts = _otp_mobile_attempts.get(mobile, 0)

    if attempts >= settings.WHATSAPP_MAX_OTP_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect OTP attempts. Please request a new OTP."
        )

    now = datetime.now(timezone.utc)
    email_key = f"wa:{mobile}"

    otp_record = (
        db.query(OtpRequest)
        .filter(
            OtpRequest.email == email_key,
            OtpRequest.used_at.is_(None),
            OtpRequest.expires_at > now
        )
        .order_by(OtpRequest.created_at.desc())
        .first()
    )

    expected_hash = _hash_otp(otp_code, mobile)

    # pyrefly: ignore [no-matching-overload]
    if not otp_record or not hmac.compare_digest(expected_hash, otp_record.otp_hash):
        # Increment attempt counter
        if r:
            r.incr(attempts_key)
            r.expire(attempts_key, 300)
        else:
            _otp_mobile_attempts[mobile] = attempts + 1

        remaining = settings.WHATSAPP_MAX_OTP_ATTEMPTS - (attempts + 1)
        if remaining > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid or expired OTP. {remaining} attempt(s) remaining."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP. Maximum attempts exceeded. Please request a new OTP."
            )

    # Invalidate OTP on success (Single-use guarantee)
    otp_record.used_at = now
    db.commit()

    if r:
        r.delete(attempts_key)
    else:
        _otp_mobile_attempts.pop(mobile, None)

    return {
        "success": True,
        "verified": True,
        "mobile": mobile,
        "message": "Mobile number verified successfully via WhatsApp."
    }
