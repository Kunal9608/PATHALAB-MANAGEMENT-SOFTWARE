"""Auth router."""
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, get_client_ip
from backend.app.schemas.auth import (
    LoginRequest, OtpRequestSchema, OtpVerifyRequest,
    PasswordResetRequest, MessageResponse
)
from backend.app.services import auth_service
from backend.app.config import settings
from backend.app.core.limiter import limiter

import os

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "60/minute")

@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
def login(payload: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)):
    from backend.app.services.recaptcha_service import verify_recaptcha_token
    from fastapi import HTTPException
    if not verify_recaptcha_token(payload.recaptcha_token):
        raise HTTPException(status_code=400, detail="reCAPTCHA verification failed. Please try again.")

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    result = auth_service.login(db, payload.email, payload.password, ip, ua)

    if not result.get("requires_password_reset"):
        # Set httpOnly cookies
        secure = settings.cookie_secure
        response.set_cookie("access_token", result["access_token"],
                            httponly=True, secure=secure, samesite="strict",
                            max_age=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)
        response.set_cookie("refresh_token", result["refresh_token"],
                            httponly=True, secure=secure, samesite="strict",
                            max_age=settings.JWT_REFRESH_EXPIRE_HOURS * 3600)

    return result


security_bearer = HTTPBearer(auto_error=False)

@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
):
    from backend.app.core.security import hash_token, decode_token
    from backend.app.repositories import session_repo as srepo
    import uuid

    # 1. Revoke session associated with refresh token cookie if present
    refresh = request.cookies.get("refresh_token")
    if refresh:
        token_hash = hash_token(refresh)
        srepo.revoke_session_by_token_hash(db, token_hash)

    # 2. Revoke session associated with access token (from Authorization header or cookie)
    access_token = None
    if credentials and credentials.credentials:
        access_token = credentials.credentials
    elif request.cookies.get("access_token"):
        access_token = request.cookies.get("access_token")

    if access_token:
        try:
            payload = decode_token(access_token)
            sid = payload.get("sid")
            if sid:
                srepo.revoke_session(db, uuid.UUID(sid))
        except Exception:
            pass

    db.commit()
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out successfully"}


@router.post("/otp/request")
@limiter.limit("3/5minute")
def request_otp(payload: OtpRequestSchema, request: Request, db: Session = Depends(get_db)):
    from backend.app.services.recaptcha_service import verify_recaptcha_token
    from fastapi import HTTPException
    if not verify_recaptcha_token(payload.recaptcha_token):
        raise HTTPException(status_code=400, detail="reCAPTCHA verification failed. Please try again.")

    ip = get_client_ip(request)
    auth_service.request_otp(db, payload.email, payload.purpose, ip)
    return {"message": "OTP sent if email is registered"}


@router.post("/otp/verify")
@limiter.limit("5/minute")
def verify_otp(payload: OtpVerifyRequest, request: Request, response: Response,
               db: Session = Depends(get_db)):
    otp_val = payload.otp or payload.otp_code
    if not otp_val:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="OTP code is required")

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")

    result = auth_service.verify_otp_code(db, payload.email, otp_val, payload.purpose, ip, ua)

    if result.get("requires_password_reset"):
        return result

    if payload.purpose == "login":
        secure = settings.cookie_secure
        response.set_cookie("access_token", result["access_token"],
                            httponly=True, secure=secure, samesite="strict",
                            max_age=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)
        response.set_cookie("refresh_token", result["refresh_token"],
                            httponly=True, secure=secure, samesite="strict",
                            max_age=settings.JWT_REFRESH_EXPIRE_HOURS * 3600)

    return result


@router.post("/password/reset")
@limiter.limit("5/minute")
def reset_password(payload: PasswordResetRequest, request: Request, response: Response,
                   db: Session = Depends(get_db)):
    from backend.app.services.auth_service import decode_token, create_access_token, create_refresh_token
    from backend.app.core.security import hash_token
    from backend.app.repositories import user_repo, session_repo as srepo
    from backend.app.services.auth_service import _parse_device_label
    import uuid

    try:
        token_payload = decode_token(payload.reset_token)
        if token_payload.get("type") != "short" or token_payload.get("purpose") != "password_reset":
            raise ValueError("Invalid token")
        user_id = token_payload.get("sub")
        if not user_id:
            raise ValueError("Invalid token: missing subject")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    try:
        auth_service.reset_password(db, payload.reset_token, payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = user_repo.get_by_id(db, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Issue session tokens
    refresh_token = create_refresh_token(str(user.id))
    token_hash = hash_token(refresh_token)

    from backend.app.dependencies import get_client_ip
    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    device_label = _parse_device_label(ua)
    session = srepo.create_session(db, user.id, token_hash, device_label, ip)
    access_token = create_access_token(str(user.id), user.role, session_id=str(session.id))
    db.commit()

    secure = settings.cookie_secure
    response.set_cookie("access_token", access_token,
                        httponly=True, secure=secure, samesite="strict",
                        max_age=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)
    response.set_cookie("refresh_token", refresh_token,
                        httponly=True, secure=secure, samesite="strict",
                        max_age=settings.JWT_REFRESH_EXPIRE_HOURS * 3600)

    return {
        "message": "Password reset and logged in successfully",
        "role": user.role,
        "user": {"id": str(user.id), "name": user.name, "role": user.role}
    }


@router.post("/refresh")
def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    refresh = request.cookies.get("refresh_token")
    if not refresh:
        raise HTTPException(status_code=401, detail="No refresh token")
    access = auth_service.refresh_access_token(db, refresh)
    if not access:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    response.set_cookie("access_token", access, httponly=True,
                        secure=settings.cookie_secure, samesite="strict",
                        max_age=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)
    return {"message": "Token refreshed"}


@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "name": current_user.name,
        "email": current_user.email,
        "mobile": getattr(current_user, 'mobile', None),
        "role": current_user.role,
        "view_scope": current_user.view_scope,
        "face_registered": current_user.face_registered,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


from pydantic import BaseModel as PydanticModel
from typing import Optional as Opt

class ProfileUpdate(PydanticModel):
    name: Opt[str] = None
    mobile: Opt[str] = None


@router.patch("/me/profile")
def update_my_profile(payload: ProfileUpdate, current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    from backend.app.repositories import user_repo
    updates = payload.model_dump(exclude_none=True)
    if updates:
        user_repo.update_user(db, current_user.id, **updates)
        db.commit()
    updated = user_repo.get_by_id(db, current_user.id)
    return {
        "id": str(updated.id),
        "name": updated.name,
        "email": updated.email,
        "mobile": getattr(updated, 'mobile', None),
        "role": updated.role,
        "view_scope": updated.view_scope,
    }


from typing import Optional

class ChangePasswordPayload(PydanticModel):
    current_password: Optional[str] = None
    otp_code: Optional[str] = None
    new_password: str


@router.post("/me/change-password")
def change_my_password(payload: ChangePasswordPayload,
                       request: Request,
                       current_user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    from backend.app.core.security import verify_password, hash_password, validate_password_policy
    from backend.app.repositories import user_repo, session_repo as srepo
    
    if not payload.current_password and not payload.otp_code:
        raise ValueError("Either current password or OTP code must be provided")

    if payload.current_password:
        is_valid, _ = verify_password(payload.current_password, current_user.password_hash)
        if not is_valid:
            raise ValueError("Current password is incorrect")
    else:
        ip = request.client.host if request.client else "0.0.0.0"
        ua = request.headers.get("user-agent")
        auth_service.verify_otp_code(db, current_user.email, payload.otp_code, "password_change", ip, ua)

    if not validate_password_policy(payload.new_password):
        raise ValueError("Password must be between 6 and 12 characters with at least one letter and one digit")
    new_hash = hash_password(payload.new_password)
    user_repo.update_user(db, current_user.id, password_hash=new_hash, must_reset_password=False)
    srepo.revoke_all_user_sessions(db, current_user.id)
    db.commit()
    return {"message": "Password changed successfully"}
