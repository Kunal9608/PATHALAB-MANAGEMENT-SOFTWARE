"""
Database engine, session factory, and base model.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from backend.app.config import settings


class Base(DeclarativeBase):
    pass


import time
import logging

logger = logging.getLogger("akriti.db")

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {
    "poolclass": QueuePool if not is_sqlite else None,
    "echo": False,
}

if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 15,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 300,  # Recycle every 5m to prevent stale sockets/leaks on Supabase
        "pool_pre_ping": True,
        "pool_use_lifo": True, # Reuse most recently used connections first to allow idle connections to be closed
        "connect_args": {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            # Statement timeout: 15s, Lock timeout: 5s, Idle in transaction timeout: 30s
            "options": "-c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000"
        }
    })
else:
    engine_kwargs.update({
        "connect_args": {"check_same_thread": False}
    })

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.time())


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    times = conn.info.get("query_start_time", [])
    if times:
        start_time = times.pop(-1)
        duration = time.time() - start_time
        clean_stmt = statement.strip()
        if duration > 2.5 and not clean_stmt.startswith("SELECT 1"):  # Log actual slow queries exceeding 2.5s
            logger.warning(
                f"SLOW SQL [{duration:.3f}s]: {statement[:200]} | params: {str(parameters)[:100]}"
            )


def get_db():
    """FastAPI dependency — yields a DB session and ensures it's closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def enable_pgvector(db_session):
    """Enable pgvector extension if available."""
    try:
        db_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db_session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        db_session.commit()
    except Exception:
        db_session.rollback()


def init_db():
    """Create all tables (used in development; production uses Alembic)."""
    from backend.app.models import (  # noqa: F401 — import all models for metadata
        user, face_embedding, attendance_event, patient, patient_test,
        test, test_price_history, doctor, franchise, report, expense,
        login_history, active_session, audit_log, otp_request,
        test_parameter, patient_test_result
    )
    Base.metadata.create_all(bind=engine)

    # Additional fallback migrations and indexes have been removed as per F-31.
    # Schema changes should strictly be managed via Alembic migrations.
