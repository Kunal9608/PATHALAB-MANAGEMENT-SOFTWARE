"""
Security utilities: password hashing, JWT encode/decode, OTP generation.
"""
import os
import random
import string
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict

import jwt
from jwt.exceptions import PyJWTError as JWTError
import bcrypt
from argon2 import PasswordHasher
from typing import Tuple

ph = PasswordHasher()

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
from backend.app.config import settings


def _apply_pepper(password: str) -> str:
    """Combines password and pepper using HMAC-SHA256 before hashing."""
    pepper = settings.PASSWORD_PEPPER.encode('utf-8')
    return hmac.new(pepper, password.encode('utf-8'), hashlib.sha256).hexdigest()

def hash_password(plain: str) -> str:
    return ph.hash(_apply_pepper(plain))


def verify_password(plain: str, hashed: str) -> Tuple[bool, bool]:
    """
    Returns (is_valid, needs_rehash).
    Handles automatic bcrypt migration and Argon2 parameter upgrades.
    """
    if hashed.startswith("$2"):
        # Legacy bcrypt hash
        pw_bytes = plain.encode('utf-8')
        hashed_bytes = hashed.encode('utf-8')
        try:
            is_valid = bcrypt.checkpw(pw_bytes, hashed_bytes)
            return (is_valid, is_valid)  # If valid, requires immediate rehash
        except Exception:
            return (False, False)
            
    # Argon2id verification
    try:
        is_valid = ph.verify(hashed, _apply_pepper(plain))
        needs_rehash = ph.check_needs_rehash(hashed)
        return (is_valid, needs_rehash)
    except Exception:
        return (False, False)


def create_access_token(user_id: str, role: str, session_id: Optional[str] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "type": "access",
    }
    if session_id:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    import uuid
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_REFRESH_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_short_lived_token(user_id: str, purpose: str = "password_reset", minutes: int = 10) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "purpose": purpose,
        "type": "short",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Raises JWTError if invalid or expired."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def generate_otp(length: int = 6) -> str:
    import secrets
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def verify_otp(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(plain.encode()).hexdigest(), hashed)


def hash_token(token: str) -> str:
    """Used to store refresh tokens hashed (never raw)."""
    return hashlib.sha256(token.encode()).hexdigest()


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def canonical_json(data: dict) -> str:
    """Stable JSON serialization for hash-chaining."""
    return json.dumps(data, sort_keys=True, default=str, ensure_ascii=True)


def validate_password_policy(password: str) -> bool:
    """FR-1.4: min 6 chars, max 12 chars, at least one letter and one digit."""
    import re
    if len(password) < 6 or len(password) > 12:
        return False
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return False
    return True
