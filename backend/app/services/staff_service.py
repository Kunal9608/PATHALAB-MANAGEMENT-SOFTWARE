"""Staff service — create staff, face enrollment gate, edit/deactivate."""
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core.security import hash_password
from backend.app.repositories import user_repo
from backend.app.services import audit_service, notification_service
from backend.app.models.user import RoleEnum, ViewScopeEnum


import hashlib
from backend.app.models.user import User


def generate_staff_code(db: Session, year: int) -> str:
    from sqlalchemy import text
    seq_name = f"staff_seq_{year}"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"))
    result = db.execute(text(f"SELECT nextval('{seq_name}')"))
    seq_val = result.scalar()
    year_short = str(year)[-2:]
    padded = str(seq_val).zfill(3)
    return f"STAFF{year_short}{padded}"


def _gen_temp_password() -> str:
    chars = string.ascii_letters + string.digits
    import re
    while True:
        pwd = "".join(secrets.choice(chars) for _ in range(10))
        if re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]{6,}$", pwd):
            return pwd


def create_staff(db: Session, payload, actor_user_id: uuid.UUID, background_tasks) -> dict:
    """FR-2.1 — Add staff. Account active immediately; temp password must be reset on first login."""
    # Check duplicate email (uses normalize_email inside repo)
    existing_email = user_repo.get_by_email(db, payload.email)
    if existing_email:
        raise ValueError("Email already registered")

    # Check duplicate mobile
    if payload.mobile:
        existing_mobile = db.query(User).filter(User.mobile == payload.mobile).first()
        if existing_mobile:
            raise ValueError("Mobile number already registered")

    # Check duplicate Aadhar
    aadhar_hash = None
    aadhar_last4 = None
    if payload.aadhar:
        aadhar_hash = hashlib.sha256(payload.aadhar.encode()).digest()
        existing_aadhar = db.query(User).filter(User.aadhar_encrypted == aadhar_hash).first()
        if existing_aadhar:
            raise ValueError("Aadhar number already registered")
        aadhar_last4 = payload.aadhar[-4:]

    temp_pw = _gen_temp_password()
    pw_hash = hash_password(temp_pw)

    # Generate staff code
    current_year = datetime.now().year
    staff_code = generate_staff_code(db, current_year)

    user = user_repo.create_user(
        db,
        role=RoleEnum.staff,
        staff_code=staff_code,
        name=payload.name,
        email=payload.email,
        password_hash=pw_hash,
        mobile=payload.mobile,
        dob=payload.dob,
        aadhar_encrypted=aadhar_hash,
        aadhar_last4=aadhar_last4,
        view_scope=payload.view_scope or "own",
        face_registered=False,
        is_active=True,            # Active immediately — no face gate
        must_reset_password=True,  # Must set own password on first login
    )

    audit_service.log(db, "staff.create", actor_user_id=actor_user_id,
                      entity_type="user", entity_id=user.id,
                      after={"name": user.name, "email": user.email, "staff_code": staff_code})
    db.commit()

    # Email credentials (using FastAPI BackgroundTasks)
    background_tasks.add_task(
        notification_service.notify,
        "welcome_staff",
        user.email,
        {"name": user.name, "temp_password": temp_pw}
    )

    return _user_to_dict(user)


def update_staff(db: Session, staff_id: uuid.UUID, payload, actor_user_id: uuid.UUID) -> dict:
    staff = user_repo.get_by_id(db, staff_id)
    if not staff or staff.role != RoleEnum.staff:
        raise ValueError("Staff not found")

    before = _user_to_dict(staff)
    updates = payload.model_dump(exclude_none=True)

    # Duplicate check for Email update
    if "email" in updates and updates["email"]:
        from backend.app.repositories.user_repo import normalize_email
        email_normalized = normalize_email(updates["email"])
        existing = db.query(User).filter(User.email == email_normalized, User.id != staff_id).first()
        if existing:
            raise ValueError("Email already registered by another staff")
        updates["email"] = email_normalized

    # Duplicate check for Mobile update
    if "mobile" in updates and updates["mobile"]:
        existing = db.query(User).filter(User.mobile == updates["mobile"], User.id != staff_id).first()
        if existing:
            raise ValueError("Mobile number already registered by another staff")

    # Duplicate check for Aadhar update
    if "aadhar" in updates:
        aadhar_val = updates.pop("aadhar")
        if aadhar_val:
            aadhar_hash = hashlib.sha256(aadhar_val.encode()).digest()
            existing = db.query(User).filter(User.aadhar_encrypted == aadhar_hash, User.id != staff_id).first()
            if existing:
                raise ValueError("Aadhar number already registered by another staff")
            updates["aadhar_encrypted"] = aadhar_hash
            updates["aadhar_last4"] = aadhar_val[-4:]

    user_repo.update_user(db, staff_id, **updates)
    audit_service.log(db, "staff.edit", actor_user_id=actor_user_id,
                      entity_type="user", entity_id=staff_id,
                      before=before, after=updates)
    db.commit()

    staff = user_repo.get_by_id(db, staff_id)
    return _user_to_dict(staff)


def deactivate_staff(db: Session, staff_id: uuid.UUID, actor_user_id: uuid.UUID) -> dict:
    staff = user_repo.get_by_id(db, staff_id)
    if not staff or staff.role != RoleEnum.staff:
        raise ValueError("Staff not found")

    user_repo.update_user(db, staff_id,
                          is_active=False,
                          deactivated_at=datetime.now(timezone.utc))
    
    from backend.app.repositories import session_repo
    session_repo.revoke_all_user_sessions(db, staff_id)
    
    audit_service.log(db, "staff.deactivate", actor_user_id=actor_user_id,
                      entity_type="user", entity_id=staff_id)
    db.commit()
    return {"message": "Staff deactivated"}


def list_staff(
    db: Session,
    include_inactive: bool = False,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
):
    if q:
        page_size = 3
    items, total = user_repo.get_staff_paginated(
        db, include_inactive=include_inactive, q=q, is_active=is_active,
        page=page, page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return {
        "items": [_user_to_dict(u) for u in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_staff(db: Session, staff_id: uuid.UUID):
    staff = user_repo.get_by_id(db, staff_id)
    if not staff or staff.role != RoleEnum.staff:
        raise ValueError("Staff not found")
    return _user_to_dict(staff)


def _user_to_dict(user) -> dict:
    return {
        "id": str(user.id),
        "staff_code": user.staff_code,
        "name": user.name,
        "email": user.email,
        "mobile": user.mobile,
        "dob": user.dob.isoformat() if user.dob else None,
        "role": user.role.value if hasattr(user.role, 'value') else str(user.role),
        "view_scope": user.view_scope.value if hasattr(user.view_scope, 'value') else str(user.view_scope),
        "face_registered": user.face_registered,
        "is_active": user.is_active,
        "aadhar_last4": user.aadhar_last4,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "deactivated_at": user.deactivated_at.isoformat() if user.deactivated_at else None,
    }


def backfill_staff_codes(db: Session):
    from datetime import datetime
    staff_members = db.query(User).filter(User.role == RoleEnum.staff).filter((User.staff_code.is_(None)) | (User.staff_code == "")).all()
    if not staff_members:
        return
    current_year = datetime.now().year
    for member in staff_members:
        member.staff_code = generate_staff_code(db, current_year)
    db.commit()
