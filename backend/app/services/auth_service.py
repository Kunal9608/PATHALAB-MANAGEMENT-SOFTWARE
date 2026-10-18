"""Authentication service — login, OTP, password reset, lockouts."""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid
import logging
import secrets
import string

from sqlalchemy.orm import Session

from fastapi import HTTPException

from backend.app.core.security import (
    verify_password, hash_password, create_access_token,
    create_refresh_token, create_short_lived_token, decode_token,
    generate_otp, hash_otp, verify_otp, hash_token,
    validate_password_policy
)
from backend.app.core.redis_client import get_redis
from backend.app.repositories import user_repo, session_repo
from backend.app.models.otp_request import OtpRequest, OtpPurposeEnum
from backend.app.services import audit_service, notification_service

logger = logging.getLogger(__name__)

import threading
import time

# Thread-safe in-memory fallback for lockouts and failed attempts
_auth_lock = threading.Lock()
_fail_counts: dict[str, tuple[float, int]] = {}   # email -> (expire_timestamp, count)
_lockouts: dict[str, float] = {}                  # email -> expire_timestamp
_otp_req_counts: dict = {}
_otp_fail_counts: dict = {}
_consumed_reset_tokens: dict[str, float] = {}     # token_identifier -> expire_timestamp


def _is_reset_token_consumed(token_identifier: str) -> bool:
    r = get_redis()
    key = f"used_reset_token:{token_identifier}"
    if r:
        try:
            return r.get(key) is not None
        except Exception as e:
            logger.warning(f"Redis check used reset token error: {e}")

    now = time.time()
    with _auth_lock:
        exp = _consumed_reset_tokens.get(token_identifier)
        if exp is not None:
            if now < exp:
                return True
            else:
                _consumed_reset_tokens.pop(token_identifier, None)
    return False


def _mark_reset_token_consumed(token_identifier: str, duration_seconds: int = 600):
    r = get_redis()
    key = f"used_reset_token:{token_identifier}"
    if r:
        try:
            r.set(key, "1", ex=duration_seconds)
            return
        except Exception as e:
            logger.warning(f"Redis set used reset token error: {e}")

    now = time.time()
    with _auth_lock:
        _consumed_reset_tokens[token_identifier] = now + float(duration_seconds)



def _redis_incr_fail(email: str) -> int:
    r = get_redis()
    key = f"fail:{email}"
    if r:
        try:
            count = r.incr(key)
            r.expire(key, 900)
            return int(count)
        except Exception as e:
            logger.warning(f"Redis fail incr error: {e}")

    now = time.time()
    with _auth_lock:
        if email in _fail_counts:
            exp, count = _fail_counts[email]
            if now < exp:
                new_count = count + 1
                _fail_counts[email] = (now + 900.0, new_count)
                return new_count
        _fail_counts[email] = (now + 900.0, 1)
        return 1


def _redis_set_lockout(email: str, duration_seconds: int = 900):
    r = get_redis()
    key = f"lockout:{email}"
    if r:
        try:
            r.set(key, "1", ex=duration_seconds)
        except Exception as e:
            logger.warning(f"Redis set lockout error: {e}")

    now = time.time()
    with _auth_lock:
        _lockouts[email] = now + float(duration_seconds)


def _redis_check_lockout(email: str) -> bool:
    r = get_redis()
    key = f"lockout:{email}"
    if r:
        try:
            val = r.get(key)
            if val is not None:
                return True
        except Exception as e:
            logger.warning(f"Redis check lockout error: {e}")

    now = time.time()
    with _auth_lock:
        exp = _lockouts.get(email)
        if exp is not None:
            if now < exp:
                return True
            else:
                _lockouts.pop(email, None)
    return False


def _redis_clear_fail(email: str):
    r = get_redis()
    if r:
        try:
            r.delete(f"fail:{email}")
            r.delete(f"lockout:{email}")
        except Exception as e:
            logger.warning(f"Redis clear fail error: {e}")

    with _auth_lock:
        _fail_counts.pop(email, None)
        _lockouts.pop(email, None)


def login(db: Session, email: str, password: str, ip: str,
          user_agent: Optional[str] = None) -> dict:
    email = email.lower().strip()
    user = user_repo.get_by_email(db, email)

    if user is None:
        session_repo.record_login(db, email, "unknown_email", ip, user_agent)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 1. Lockout check — Expiry-aware evaluation
    is_active_lockout = _redis_check_lockout(email)

    if not is_active_lockout and getattr(user, "is_locked", False):
        # Database flag is set. Check if the 15-minute window has elapsed using LoginHistory
        from backend.app.models.login_history import LoginHistory, LoginOutcomeEnum
        last_lock = (
            db.query(LoginHistory)
            .filter(LoginHistory.user_id == user.id, LoginHistory.outcome == LoginOutcomeEnum.locked_out)
            .order_by(LoginHistory.attempted_at.desc())
            .first()
        )
        now_utc = datetime.now(timezone.utc)
        if last_lock and last_lock.attempted_at:
            attempted_at = last_lock.attempted_at
            if attempted_at.tzinfo is None:
                attempted_at = attempted_at.replace(tzinfo=timezone.utc)
            lock_age = (now_utc - attempted_at).total_seconds()
            if lock_age < 900:
                is_active_lockout = True
                _redis_set_lockout(email, int(900 - lock_age))

        if not is_active_lockout:
            # 15-minute temporary lockout has expired! Automatically unlock user.
            user.is_locked = False
            _redis_clear_fail(email)
            db.commit()

    if is_active_lockout or getattr(user, "is_locked", False):
        session_repo.record_login(db, email, "locked_out", ip, user_agent, user.id)
        db.commit()
        raise PermissionError("Account temporarily locked due to multiple failed attempts. Please wait 15 minutes or login via OTP to unlock.")

    if not user.is_active and not user.must_reset_password:
        raise PermissionError("Account is inactive. Contact the administrator.")

    is_valid, needs_rehash = verify_password(password, user.password_hash)
    if not is_valid:
        count = _redis_incr_fail(email)
        if count >= 5:
            user.is_locked = True
            _redis_set_lockout(email, 900)
            session_repo.record_login(db, email, "locked_out", ip, user_agent, user.id)
            db.commit()
            raise PermissionError("Account locked due to 5 failed attempts. Please wait 15 minutes or login via OTP to unlock.")
        session_repo.record_login(db, email, "bad_password", ip, user_agent, user.id)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if needs_rehash:
        user.password_hash = hash_password(password)
        db.commit()

    _redis_clear_fail(email)
    if getattr(user, "is_locked", False):
        user.is_locked = False
        db.commit()

    # Duplicate login block: auto-logout older sessions on other devices
    session_repo.revoke_all_user_sessions(db, user.id)

    session_repo.record_login(db, email, "success", ip, user_agent, user.id)

    if user.must_reset_password:
        reset_token = create_short_lived_token(str(user.id), "password_reset")
        db.commit()
        return {
            "requires_password_reset": True,
            "reset_token": reset_token,
            "role": user.role,
            "user": {"id": str(user.id), "name": user.name, "role": user.role},
        }

    refresh_token = create_refresh_token(str(user.id))
    token_hash = hash_token(refresh_token)

    # Parse user agent for device label
    device_label = _parse_device_label(user_agent or "")
    session = session_repo.create_session(db, user.id, token_hash, device_label, ip)
    access_token = create_access_token(str(user.id), user.role, session_id=str(session.id))
    db.commit()

    return {
        "requires_password_reset": False,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user.role,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "role": user.role,
            "email": user.email,
        },
    }


def request_otp(db: Session, email: str, purpose: str, ip: str) -> bool:
    email = email.lower().strip()

    # Rate limiting: max 3 OTPs per 10 min per email
    r = get_redis()
    if r:
        rl_key = f"otp_rate:{email}"
        count = r.get(rl_key)
        if count and int(count) >= 3:
            raise PermissionError("Too many OTP requests. Please wait 10 minutes.")
        r.incr(rl_key)
        r.expire(rl_key, 600)
    else:
        # In-memory fallback
        now = datetime.now()
        reqs = _otp_req_counts.get(email, [])
        reqs = [t for t in reqs if (now - t).total_seconds() < 600]
        if len(reqs) >= 3:
            raise PermissionError("Too many OTP requests. Please wait 10 minutes.")
        reqs.append(now)
        _otp_req_counts[email] = reqs

    user = user_repo.get_by_email(db, email)
    if not user:
        # Prevent account enumeration: return True silently without creating OTP or revealing email absence
        logger.info(f"OTP request for unregistered email suppressed: {email}")
        return True

    otp = generate_otp()
    otp_hash_val = hash_otp(otp)
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)

    otp_obj = OtpRequest(
        email=email,
        otp_hash=otp_hash_val,
        purpose=purpose,
        expires_at=expires,
        requesting_ip=ip,
    )
    db.add(otp_obj)
    db.commit()

    # Map OTP purpose to appropriate notification template
    event_type_map = {
        "login": "otp",
        "password_reset": "password_reset",
        "password_change": "password_change",
        "delete_verify": "delete_verify",
    }
    event_type = event_type_map.get(purpose, "otp")

    # Send notification synchronously so failures throw a 503 instead of silent failing
    try:
        notification_service.notify(event_type, email, {"otp": otp, "name": user.name})
    except Exception as e:
        logger.error(f"Failed to send OTP to {email}: {e}")
        # Delete the unused OTP request if sending failed
        db.delete(otp_obj)
        db.commit()
        raise PermissionError("Failed to send OTP. Please check service configuration.")
        
    # Reset OTP failure counter for this email
    if r:
        r.delete(f"otp_fail:{email}")
    else:
        _otp_fail_counts.pop(email, None)

    return True


def verify_otp_code(db: Session, email: str, otp_code: str, purpose: str,
                    ip: Optional[str] = None, user_agent: Optional[str] = None) -> dict:
    if not otp_code or not otp_code.isdigit():
        raise ValueError("OTP must contain only numeric characters")
        
    email = email.lower().strip()
    now = datetime.now(timezone.utc)

    otp_obj = (
        db.query(OtpRequest)
        .filter(
            OtpRequest.email == email,
            OtpRequest.purpose == purpose,
            OtpRequest.used_at.is_(None),
            OtpRequest.expires_at > now,
        )
        .order_by(OtpRequest.created_at.desc())
        .first()
    )

    if not otp_obj or not verify_otp(otp_code, otp_obj.otp_hash):
        session_repo.record_login(db, email, "bad_otp", ip or "0.0.0.0", user_agent)
        
        # Track OTP failures to prevent brute-forcing
        r = get_redis()
        fail_count = 0
        if r:
            fail_key = f"otp_fail:{email}"
            fail_count = r.incr(fail_key)
            r.expire(fail_key, 300)
        else:
            fail_count = _otp_fail_counts.get(email, 0) + 1
            _otp_fail_counts[email] = fail_count
            
        if fail_count >= 3:
            if otp_obj:
                otp_obj.used_at = now  # Invalidate the current OTP request
            _redis_set_lockout(email)  # Lock the user out for 15 minutes
            user = user_repo.get_by_email(db, email)
            if user:
                user.is_locked = True
                session_repo.record_login(db, email, "locked_out", ip or "0.0.0.0", user_agent, user.id)
            db.commit()
            raise PermissionError("Too many incorrect OTP attempts. Account locked for 15 minutes.")
            
        db.commit()
        raise ValueError("Invalid or expired OTP")

    otp_obj.used_at = now
    user = user_repo.get_by_email(db, email)
    if not user or not user.is_active:
        db.commit()
        raise ValueError("User inactive or not found")

    # Unlock user account on successful OTP verification
    if getattr(user, "is_locked", False):
        user.is_locked = False
        _redis_clear_fail(email)
        logger.info(f"User {email} unlocked via successful OTP verification")

    # Duplicate login block: auto-logout older sessions on other devices
    session_repo.revoke_all_user_sessions(db, user.id)

    if purpose == "password_reset":
        reset_token = create_short_lived_token(str(user.id), "password_reset")
        db.commit()
        return {
            "requires_password_reset": True,
            "reset_token": reset_token,
            "role": user.role,
            "user": {"id": str(user.id), "name": user.name, "role": user.role},
        }

    # For login via OTP
    if user.must_reset_password:
        reset_token = create_short_lived_token(str(user.id), "password_reset")
        db.commit()
        return {
            "requires_password_reset": True,
            "reset_token": reset_token,
            "role": user.role,
            "user": {"id": str(user.id), "name": user.name, "role": user.role},
        }

    refresh_token = create_refresh_token(str(user.id))
    token_hash = hash_token(refresh_token)
    device_label = _parse_device_label(user_agent or "")
    session = session_repo.create_session(db, user.id, token_hash, device_label, ip)
    access_token = create_access_token(str(user.id), user.role, session_id=str(session.id))
    db.commit()
    return {
        "requires_password_reset": False,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user.role,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "role": user.role,
            "email": user.email,
        },
    }


def reset_password(db: Session, reset_token: str, new_password: str) -> bool:
    try:
        payload = decode_token(reset_token)
        if payload.get("type") != "short" or payload.get("purpose") != "password_reset":
            raise ValueError("Invalid token")
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Invalid token")
    except Exception:
        raise ValueError("Invalid or expired reset token")

    # Replay protection: check if reset token was already consumed
    jti = payload.get("jti")
    token_identifier = jti or hash_token(reset_token)
    if _is_reset_token_consumed(token_identifier):
        raise ValueError("Reset token has already been used")

    if not validate_password_policy(new_password):
        raise ValueError("Password must be between 6 and 12 characters with at least one letter and one digit")

    user = user_repo.get_by_id(db, uuid.UUID(user_id))
    if not user:
        raise ValueError("User not found")

    new_hash = hash_password(new_password)
    user_repo.update_user(db, user.id,
                          password_hash=new_hash,
                          must_reset_password=False,
                          is_active=True)

    # Revoke all existing sessions for security
    session_repo.revoke_all_user_sessions(db, user.id)

    # Mark reset token as consumed for its remaining lifetime
    exp_claim = payload.get("exp")
    if exp_claim:
        now_ts = datetime.now(timezone.utc).timestamp()
        duration = max(60, int(exp_claim - now_ts))
    else:
        duration = 600
    _mark_reset_token_consumed(token_identifier, duration)

    audit_service.log(db, "auth.password_reset", actor_user_id=user.id,
                      entity_type="user", entity_id=user.id)
    db.commit()
    return True


def refresh_access_token(db: Session, refresh_token: str) -> Optional[str]:
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            return None
        user_id = payload["sub"]
    except Exception:
        return None

    token_hash = hash_token(refresh_token)
    session = session_repo.get_session_by_token_hash(db, token_hash)
    if not session or session.revoked_at:
        # Check if the token was previously revoked (reuse detection / possible breach)
        from backend.app.models.active_session import ActiveSession
        revoked_sess = db.query(ActiveSession).filter(
            ActiveSession.refresh_token_hash == token_hash,
            ActiveSession.revoked_at.isnot(None)
        ).first()
        if revoked_sess:
            logger.warning(
                f"Security alert: attempt to use revoked refresh token for user {user_id}, "
                f"session {revoked_sess.id}"
            )
        return None

    user = user_repo.get_by_id(db, uuid.UUID(user_id))
    if not user or not user.is_active:
        return None

    session_repo.update_session_activity(db, session.id)
    db.commit()
    return create_access_token(str(user.id), user.role, session_id=str(session.id))


def generate_temp_password(length: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(chars) for _ in range(length))
        if validate_password_policy(pwd):
            return pwd


def _parse_device_label(user_agent: str) -> str:
    ua = user_agent.lower()
    if "mobile" in ua or "android" in ua:
        return "Mobile Device"
    elif "ipad" in ua or "tablet" in ua:
        return "Tablet"
    elif "chrome" in ua:
        return "Chrome Browser"
    elif "firefox" in ua:
        return "Firefox Browser"
    elif "safari" in ua:
        return "Safari Browser"
    return "Unknown Device"
