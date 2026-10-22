"""Attendance service — check-in/out logic, reporting."""
import uuid
from datetime import date, datetime, timedelta
from typing import Optional, List

from sqlalchemy.orm import Session

from backend.app.repositories import attendance_repo, user_repo
from backend.app.services import audit_service, face_service


def log_attendance(db: Session, user_id: uuid.UUID, confidence: float,
                   device_id: Optional[str] = None, source: str = "online") -> dict:
    """FR-3.1 — Determine check_in or check_out based on last event today with 60s cooldown."""
    from datetime import timezone
    last_event = attendance_repo.get_last_event_today(db, user_id)

    # 60-second debounce check to prevent accidental double punch / flip-flop
    now = datetime.now(timezone.utc)
    if last_event and last_event.event_time:
        event_time = last_event.event_time
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        elapsed_seconds = (now - event_time).total_seconds()
        if elapsed_seconds < 60:
            user = user_repo.get_by_id(db, user_id)
            user_name = user.name if user else "Staff"
            wait_sec = max(1, int(60 - elapsed_seconds))
            raise ValueError(f"Punch already recorded for {user_name} recently. Please wait {wait_sec}s before punching again.")

    # If no event today or last was check_out → check_in; else check_out
    if last_event is None or last_event.event_type == "check_out":
        event_type = "check_in"
    else:
        event_type = "check_out"

    event = attendance_repo.insert_event(
        db, user_id, event_type, confidence, device_id, source
    )

    user = user_repo.get_by_id(db, user_id)
    audit_service.log(
        db, f"attendance.{event_type}",
        actor_user_id=user_id,
        entity_type="attendance_event",
        entity_id=event.id,
        after={"event_type": event_type, "confidence": confidence},
    )
    db.commit()

    return {
        "id": str(event.id),
        "user_id": str(user_id),
        "user_name": user.name if user else "Unknown",
        "event_type": event_type,
        "matched_confidence": float(confidence),
        "event_time": event.event_time.isoformat(),
        "message": f"{'Checked in' if event_type == 'check_in' else 'Checked out'}: {user.name if user else 'Unknown'}",
    }


def recognize_and_log(db: Session, image_bytes: bytes,
                      device_id: Optional[str] = None) -> dict:
    """FR-3.1 + FR-3.2 — Face recognition pipeline."""
    result = face_service.recognize(db, image_bytes)

    if not result["matched"]:
        # FR-3.2: Low-confidence fallback — do NOT silently log
        return {
            "matched": False,
            "reason": result.get("reason", "Face not recognized"),
            "confidence": result.get("confidence", 0.0),
        }

    user_id = uuid.UUID(result["user_id"])
    confidence = result["confidence"]

    try:
        return log_attendance(db, user_id, confidence, device_id)
    except ValueError as e:
        return {
            "matched": True,
            "cooldown": True,
            "reason": str(e),
            "confidence": confidence,
            "message": str(e)
        }



def get_attendance_report(
    db: Session,
    date_from: date,
    date_to: date,
    user_id: Optional[uuid.UUID] = None,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    """FR-3.3 — Daily attendance report with frontend-compatible field names."""
    events = attendance_repo.get_events_for_range(db, date_from, date_to, user_id)

    # Group by user + date
    grouped: dict = {}
    for event in events:
        key = (str(event.user_id), str(event.event_time.date()))
        if key not in grouped:
            grouped[key] = {
                "user_id": str(event.user_id),
                "user_name": event.user.name if event.user else "Unknown",
                "date": str(event.event_time.date()),
                "check_in": None,
                "check_out": None,
                "check_in_event_time": None,
                "check_out_event_time": None,
                "confidence": None,
            }
        if event.event_type == "check_in" and grouped[key]["check_in"] is None:
            grouped[key]["check_in"] = event.event_time.strftime("%H:%M:%S")
            grouped[key]["check_in_event_time"] = event.event_time.isoformat()
            grouped[key]["confidence"] = float(event.matched_confidence or 1.0)
        if event.event_type == "check_out":
            grouped[key]["check_out"] = event.event_time.strftime("%H:%M:%S")
            grouped[key]["check_out_event_time"] = event.event_time.isoformat()

    # Compute hours and late/early flags
    results = []
    for entry in grouped.values():
        hours = None
        if entry["check_in"] and entry["check_out"]:
            fmt = "%H:%M:%S"
            ci = datetime.strptime(entry["check_in"], fmt)
            co = datetime.strptime(entry["check_out"], fmt)
            hours = round((co - ci).total_seconds() / 3600, 2)

        results.append({
            # original field names
            "user_id": entry["user_id"],
            "user_name": entry["user_name"],
            "date": entry["date"],
            "check_in": entry["check_in"],
            "check_out": entry["check_out"],
            "hours_present": hours,
            "is_late": entry["check_in"] > "09:30:00" if entry["check_in"] else False,
            "is_early_leave": (entry["check_out"] < "17:30:00" if entry["check_out"] else False),
            # frontend-compatible aliases
            "staff_name": entry["user_name"],
            "check_in_time": entry["check_in_event_time"],
            "check_out_time": entry["check_out_event_time"],
            "matched_confidence": entry["confidence"],
        })

    results = sorted(results, key=lambda x: (x["date"], x["user_name"]))

    # Paginate
    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    items = results[start:end]
    total_pages = (total + page_size - 1) // page_size

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
