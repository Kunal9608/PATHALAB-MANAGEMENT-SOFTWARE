"""Security router — sessions, login history, audit logs."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
import uuid

from backend.app.core.db import get_db
from backend.app.dependencies import get_current_user, require_admin
from backend.app.repositories import session_repo, audit_repo
from backend.app.services.audit_service import verify_chain

router = APIRouter(tags=["security"])

sessions_router = APIRouter(prefix="/sessions")
history_router = APIRouter(prefix="/login-history")
audit_router = APIRouter(prefix="/audit-logs")


# --- Sessions ---
@sessions_router.get("/mine")
@sessions_router.get("")
def my_sessions(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = session_repo.get_user_sessions(db, current_user.id)
    return [
        {
            "id": str(s.id),
            "device_label": s.device_label,
            "ip_address": s.ip_address,
            "issued_at": s.issued_at.isoformat() if s.issued_at else None,
            "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
        }
        for s in sessions
    ]


@sessions_router.post("/{session_id}/revoke")
def revoke_session(session_id: uuid.UUID, current_user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from backend.app.models.user import RoleEnum
    from backend.app.models.active_session import ActiveSession
    from fastapi import HTTPException

    sess = db.query(ActiveSession).filter(ActiveSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    # Non-admin users can ONLY revoke their own sessions
    if current_user.role != RoleEnum.admin and sess.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to revoke this session")

    ok = session_repo.revoke_session(db, session_id)
    db.commit()
    return {"message": "Session revoked"}


@sessions_router.get("/all")
def all_sessions(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: see all active sessions."""
    from backend.app.models.active_session import ActiveSession
    from sqlalchemy.orm import joinedload
    sessions = db.query(ActiveSession).options(joinedload(ActiveSession.user)).filter(ActiveSession.revoked_at.is_(None)).all()
    return [
        {
            "id": str(s.id),
            "user_id": str(s.user_id),
            "user_name": s.user.name if s.user else "User",
            "device_label": s.device_label,
            "ip_address": s.ip_address,
            "issued_at": s.issued_at.isoformat() if s.issued_at else None,
        }
        for s in sessions
    ]


# --- Login History ---
@history_router.get("")
def login_history(
    user_id: Optional[uuid.UUID] = None,
    outcome: Optional[str] = None,
    page: int = 1, page_size: int = 50,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Staff can only see their own; Admin sees all
    from backend.app.models.user import RoleEnum
    if current_user.role != RoleEnum.admin:
        user_id = current_user.id

    items, total = session_repo.get_login_history(db, user_id, page, page_size, outcome)
    return {
        "items": [
            {
                "id": str(h.id),
                "email_attempted": h.email_attempted,
                "outcome": h.outcome,
                "ip_address": h.ip_address,
                "user_agent": h.user_agent,
                "attempted_at": h.attempted_at.isoformat() if h.attempted_at else None,
                "user_name": h.user.name if h.user else None,
            }
            for h in items
        ],
        "total": total,
    }


# --- Audit Logs ---
@audit_router.get("")
def list_audit_logs(
    action: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    df = datetime.combine(date_from, datetime.min.time()) if date_from else None
    dt = datetime.combine(date_to, datetime.max.time()) if date_to else None
    items, total = audit_repo.get_logs(db, page, page_size, action, user_id, df, dt)
    return {
        "items": [
            {
                "id": h.id,
                "action": h.action,
                "entity_type": h.entity_type,
                "entity_id": str(h.entity_id) if h.entity_id else None,
                "before_value": h.before_value,
                "after_value": h.after_value,
                "ip_address": h.ip_address,
                "occurred_at": h.occurred_at.isoformat() if h.occurred_at else None,
                "record_hash": h.record_hash[:16] + "...",  # truncated for display
                "actor_name": h.actor.name if h.actor else "System",
            }
            for h in items
        ],
        "total": total,
    }


@audit_router.get("/verify-chain")
def check_chain_integrity(admin=Depends(require_admin), db: Session = Depends(get_db)):
    is_valid, bad_id = verify_chain(db)
    return {"chain_valid": is_valid, "first_bad_id": bad_id}


router.include_router(sessions_router)
router.include_router(history_router)
router.include_router(audit_router)
