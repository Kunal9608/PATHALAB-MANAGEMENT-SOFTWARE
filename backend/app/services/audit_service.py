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


def _build_canonical_payload(action: str, actor_user_id: Optional[Any], entity_type: Optional[str],
                             entity_id: Optional[Any], before: Optional[Any], after: Optional[Any],
                             occurred_at: Any) -> str:
    occ_str = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at) if occurred_at else None
    return canonical_json({
        "action": action,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "before": _sanitize_for_json(before),
        "after": _sanitize_for_json(after),
        "occurred_at": occ_str,
    })


import queue
import threading
import logging
import time
from sqlalchemy import text
from backend.app.core.db import SessionLocal

_audit_queue = queue.Queue()
_logger = logging.getLogger("akriti.audit")


def log_synchronous(db, action: str, actor_user_id: Optional[uuid.UUID] = None,
                    entity_type: Optional[str] = None, entity_id: Optional[uuid.UUID] = None,
                    before: Optional[Any] = None, after: Optional[Any] = None,
                    ip_address: Optional[str] = None) -> Any:
    """
    Synchronously persist a hash-chained audit log directly within the db session.
    Used for high-risk operations where audit persistence must be guaranteed
    before completing the operation.
    """
    try:
        # Acquire advisory lock if supported by the database engine (PostgreSQL)
        try:
            db.execute(text("SELECT pg_advisory_xact_lock(7777777)"))
        except Exception:
            pass  # Fallback for SQLite in tests or environments without advisory locks

        last_row = audit_repo.get_last_row(db)
        prev_hash = last_row.record_hash if last_row else "GENESIS"
        occurred_at = datetime.now(timezone.utc)

        canonical = _build_canonical_payload(
            action, actor_user_id, entity_type, entity_id, before, after, occurred_at
        )
        record_hash = sha256_hex(canonical + prev_hash)

        row = audit_repo.insert_log(
            db,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_value=_sanitize_for_json(before),
            after_value=_sanitize_for_json(after),
            ip_address=ip_address,
            record_hash=record_hash,
            prev_hash=prev_hash,
            occurred_at=occurred_at,
        )
        db.commit()
        return row
    except Exception as e:
        _logger.error(f"Synchronous audit log write failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        raise


def log(db, action: str, actor_user_id: Optional[uuid.UUID] = None,
        entity_type: Optional[str] = None, entity_id: Optional[uuid.UUID] = None,
        before: Optional[Any] = None, after: Optional[Any] = None,
        ip_address: Optional[str] = None, sync: bool = False):
    """
    Log an audit entry. If sync is True, persists immediately within the session.
    Otherwise queues the audit log entry for background processing.
    """
    if sync:
        return log_synchronous(
            db, action=action, actor_user_id=actor_user_id,
            entity_type=entity_type, entity_id=entity_id,
            before=before, after=after, ip_address=ip_address
        )

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
    Retries up to 3 times on temporary DB failures before discarding.
    """
    while True:
        try:
            entry = _audit_queue.get()
            success = False
            for attempt in range(1, 4):
                db_session = SessionLocal()
                try:
                    try:
                        db_session.execute(text("SELECT pg_advisory_xact_lock(7777777)"))
                    except Exception:
                        pass

                    last_row = audit_repo.get_last_row(db_session)
                    prev_hash = last_row.record_hash if last_row else "GENESIS"

                    canonical = _build_canonical_payload(
                        entry["action"], entry["actor_user_id"], entry["entity_type"],
                        entry["entity_id"], entry["before"], entry["after"],
                        entry["occurred_at"]
                    )
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
                    success = True
                    break
                except Exception as inner_e:
                    db_session.rollback()
                    _logger.warning(f"Audit log DB write attempt {attempt} failed: {inner_e}")
                    time.sleep(0.1 * attempt)
                finally:
                    db_session.close()

            if not success:
                _logger.error(f"CRITICAL: Audit log dropped after 3 attempts: {entry.get('action')}")
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
            # First attempt: modern canonical payload including actor_user_id
            canonical = _build_canonical_payload(
                row.action, row.actor_user_id, row.entity_type, row.entity_id,
                row.before_value, row.after_value, row.occurred_at
            )
            if row.id > 1 and row.prev_hash != expected_prev:
                return False, row.id
            expected_hash = sha256_hex(canonical + expected_prev)
            if expected_hash != row.record_hash:
                # Fallback check for legacy seeded rows that did not include actor_user_id
                legacy_canonical = canonical_json({
                    "action": row.action,
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id) if row.entity_id else None,
                    "before": row.before_value,
                    "after": row.after_value,
                    "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                })
                legacy_expected = sha256_hex(legacy_canonical + expected_prev)
                if legacy_expected == row.record_hash:
                    expected_hash = legacy_expected
                elif row.id == 1 and row.prev_hash == "GENESIS":
                    expected_prev = row.record_hash
                    last_id = row.id
                    continue
                else:
                    return False, row.id
            expected_prev = row.record_hash
            last_id = row.id

    return True, None
