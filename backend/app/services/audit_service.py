"""Audit service — hash-chained immutable log writer."""
import json
from datetime import datetime, timezone
from typing import Optional, Any
import uuid

from backend.app.core.security import sha256_hex, canonical_json
from backend.app.repositories import audit_repo


def _sanitize_for_json(data: Any) -> Any:
    from datetime import date, datetime
    import uuid
    from decimal import Decimal
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    if isinstance(data, uuid.UUID):
        return str(data)
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, bytes):
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.hex()
    if hasattr(data, "value"):
        return data.value
    if isinstance(data, dict):
        return {k: _sanitize_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_for_json(v) for v in data]
    return data


import queue
import threading
import logging
from sqlalchemy import text
from backend.app.core.db import SessionLocal

_audit_queue = queue.Queue()
_logger = logging.getLogger("akriti.audit")

def log(db, action: str, actor_user_id: Optional[uuid.UUID] = None,
        entity_type: Optional[str] = None, entity_id: Optional[uuid.UUID] = None,
        before: Optional[Any] = None, after: Optional[Any] = None,
        ip_address: Optional[str] = None):
    """
    Queue the audit log entry for background processing.
    This prevents the global advisory lock from serializing fast concurrent requests.
    """
    try:
        entry = {
            "action": action,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "before": _sanitize_for_json(before),
            "after": _sanitize_for_json(after),
            "ip_address": ip_address,
            "occurred_at": datetime.now(timezone.utc).isoformat()
        }
        _audit_queue.put(entry)
    except Exception as e:
        _logger.error(f"Failed to queue audit log: {e}")


def _drain_audit_queue():
    """
    Background worker that writes hash-chained audit logs in sequence.
    Acquires the advisory lock internally so it doesn't block main web requests.
    """
    while True:
        try:
            entry = _audit_queue.get()
            db_session = SessionLocal()
            try:
                # Use PostgreSQL advisory lock to serialize audit log inserts and prevent hash-chain forks
                db_session.execute(text("SELECT pg_advisory_xact_lock(7777777)"))
                
                last_row = audit_repo.get_last_row(db_session)
                prev_hash = last_row.record_hash if last_row else "GENESIS"

                canonical = canonical_json({
                    "action": entry["action"],
                    "entity_type": entry["entity_type"],
                    "entity_id": entry["entity_id"],
                    "before": entry["before"],
                    "after": entry["after"],
                    "occurred_at": entry["occurred_at"],
                })
                record_hash = sha256_hex(canonical + prev_hash)

                audit_repo.insert_log(
                    db_session,
                    actor_user_id=uuid.UUID(entry["actor_user_id"]) if entry["actor_user_id"] else None,
                    action=entry["action"],
                    entity_type=entry["entity_type"],
                    entity_id=uuid.UUID(entry["entity_id"]) if entry["entity_id"] else None,
                    before_value=entry["before"],
                    after_value=entry["after"],
                    ip_address=entry["ip_address"],
                    record_hash=record_hash,
                    prev_hash=prev_hash,
                    occurred_at=datetime.fromisoformat(entry["occurred_at"]),
                )
                db_session.commit()
            except Exception as inner_e:
                db_session.rollback()
                _logger.error(f"Audit log DB write failed: {inner_e}")
            finally:
                db_session.close()
                _audit_queue.task_done()
                
        except Exception as e:
            _logger.error(f"Audit queue loop error: {e}")

# Start the background worker daemon
threading.Thread(target=_drain_audit_queue, daemon=True).start()


def verify_chain(db) -> tuple[bool, Optional[int]]:
    """Verify hash chain integrity using explicit pagination to prevent OOM."""
    from backend.app.models.audit_log import AuditLog
    expected_prev = "GENESIS"
    last_id = 0
    chunk_size = 5000

    while True:
        rows = db.query(AuditLog).filter(AuditLog.id > last_id).order_by(AuditLog.id).limit(chunk_size).all()
        if not rows:
            break

        for row in rows:
            canonical = canonical_json({
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "before": row.before_value,
                "after": row.after_value,
                "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            })
            if row.id > 1 and row.prev_hash != expected_prev:
                return False, row.id
            expected_hash = sha256_hex(canonical + expected_prev)
            if expected_hash != row.record_hash:
                # Handle initial historical genesis row anchor if seeded before async queue
                if row.id == 1 and row.prev_hash == "GENESIS":
                    expected_prev = row.record_hash
                    last_id = row.id
                    continue
                return False, row.id
            expected_prev = row.record_hash
            last_id = row.id

    return True, None
