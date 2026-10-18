"""FastAPI shared dependencies — get_current_user, require_role, idempotency."""
from fastapi import Depends, HTTPException, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from backend.app.core.db import get_db
from backend.app.core.security import decode_token
from backend.app.repositories import user_repo
from backend.app.models.user import User, RoleEnum, ViewScopeEnum

security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """Extract and verify JWT from Authorization header or access_token cookie."""
    token = None

    # Try Authorization header first
    if credentials and credentials.credentials:
        token = credentials.credentials

    # Fall back to httpOnly cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(status_code=401, detail="Invalid token type: access token required")

    user_id = payload.get("sub")
    sid = payload.get("sid")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not sid:
        raise HTTPException(status_code=401, detail="Session has been terminated or is invalid")

    from backend.app.models.active_session import ActiveSession
    session = db.query(ActiveSession).filter(ActiveSession.id == uuid.UUID(sid)).first()
    if not session or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Session has been terminated by another device login")

    user = user_repo.get_by_id(db, uuid.UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or not found")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    user_role = getattr(current_user.role, "value", current_user.role)
    if user_role != RoleEnum.admin and user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_role(allowed_roles: list):
    def dep(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dep


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP.
    Only trust X-Forwarded-For when the direct connection comes from a private/loopback address
    (i.e., behind a genuine reverse proxy like nginx). This prevents IP spoofing via forged headers
    on direct connections, which could bypass rate limiting.
    """
    import ipaddress

    direct_ip = request.client.host if request.client else "0.0.0.0"
    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        try:
            addr = ipaddress.ip_address(direct_ip)
            # Only trust proxy header if direct connection is from private/loopback network
            if addr.is_private or addr.is_loopback:
                return forwarded.split(",")[0].strip()
        except ValueError:
            pass

    return direct_ip


def get_idempotency_key(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
) -> Optional[str]:
    """Extract Idempotency-Key header — required on mutating endpoints."""
    return idempotency_key


def check_patient_access(current_user: User, patient) -> None:
    """Enforce patient access scope: admin, full scope, or own registered patients."""
    user_role = getattr(current_user.role, "value", current_user.role)
    if user_role == RoleEnum.admin or user_role == "admin":
        return
    user_scope = getattr(current_user.view_scope, "value", current_user.view_scope)
    if user_scope == ViewScopeEnum.all or user_scope == "all":
        return
    if str(getattr(patient, "collected_by", None)) == str(current_user.id):
        return
    raise HTTPException(
        status_code=403,
        detail="You do not have permission to view or modify this patient record"
    )

