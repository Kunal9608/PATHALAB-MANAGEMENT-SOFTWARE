"""Session and login history repositories."""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from backend.app.models.active_session import ActiveSession
from backend.app.models.login_history import LoginHistory


def create_session(db: Session, user_id: uuid.UUID, refresh_token_hash: str,
                   device_label: Optional[str] = None, ip_address: Optional[str] = None) -> ActiveSession:
    session = ActiveSession(
        user_id=user_id,
        refresh_token_hash=refresh_token_hash,
        device_label=device_label,
        ip_address=ip_address,
    )
    db.add(session)
    db.flush()
    return session


def get_session_by_token_hash(db: Session, token_hash: str) -> Optional[ActiveSession]:
    return db.query(ActiveSession).filter(
        ActiveSession.refresh_token_hash == token_hash,
        ActiveSession.revoked_at.is_(None)
    ).first()


def get_user_sessions(db: Session, user_id: uuid.UUID) -> List[ActiveSession]:
    return (
        db.query(ActiveSession)
        .filter(ActiveSession.user_id == user_id, ActiveSession.revoked_at.is_(None))
        .order_by(desc(ActiveSession.last_active_at))
        .all()
    )


def revoke_session(db: Session, session_id: uuid.UUID) -> bool:
    session = db.query(ActiveSession).filter(ActiveSession.id == session_id).first()
    if not session:
        return False
    session.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return True


def revoke_user_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Revoke a session only if it belongs to the specified user."""
    session = db.query(ActiveSession).filter(
        ActiveSession.id == session_id,
        ActiveSession.user_id == user_id,
        ActiveSession.revoked_at.is_(None)
    ).first()
    if not session:
        return False
    session.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return True


def revoke_session_by_token_hash(db: Session, token_hash: str, user_id: Optional[uuid.UUID] = None) -> bool:
    """Revoke a session by token hash, optionally verifying user ownership."""
    q = db.query(ActiveSession).filter(
        ActiveSession.refresh_token_hash == token_hash,
        ActiveSession.revoked_at.is_(None)
    )
    if user_id is not None:
        q = q.filter(ActiveSession.user_id == user_id)
    session = q.first()
    if not session:
        return False
    session.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return True


def revoke_all_user_sessions(db: Session, user_id: uuid.UUID):
    db.query(ActiveSession).filter(
        ActiveSession.user_id == user_id,
        ActiveSession.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)})
    db.flush()


def update_session_activity(db: Session, session_id: uuid.UUID):
    session = db.query(ActiveSession).filter(ActiveSession.id == session_id).first()
    if session:
        session.last_active_at = datetime.now(timezone.utc)
        db.flush()


def record_login(db: Session, email: str, outcome: str, ip: str,
                 user_agent: Optional[str] = None, user_id: Optional[uuid.UUID] = None) -> LoginHistory:
    record = LoginHistory(
        user_id=user_id,
        email_attempted=email.lower(),
        outcome=outcome,
        ip_address=ip,
        user_agent=user_agent,
    )
    db.add(record)
    db.flush()
    return record


def get_login_history(db: Session, user_id: Optional[uuid.UUID] = None,
                      page: int = 1, page_size: int = 50,
                      outcome: Optional[str] = None) -> tuple:
    q = db.query(LoginHistory).options(joinedload(LoginHistory.user))
    if user_id:
        q = q.filter(LoginHistory.user_id == user_id)
    if outcome:
        q = q.filter(LoginHistory.outcome == outcome)
    count_q = q.limit(1000).subquery()
    total = db.query(count_q).count()
    items = q.order_by(desc(LoginHistory.attempted_at)).offset((page - 1) * page_size).limit(page_size).all()
    return items, total
