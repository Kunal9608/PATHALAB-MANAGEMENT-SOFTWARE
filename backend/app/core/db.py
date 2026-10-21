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
    is_supabase_session_pooler = "pooler.supabase.com" in settings.DATABASE_URL and ":6543" not in settings.DATABASE_URL
    if is_supabase_session_pooler:
        # Supabase pooler on port 5432 enforces strict upstream limit of 15 clients per pool.
        # Keeping local pool at 10+3=13 connections ensures requests queue in memory
        # rather than being terminated by upstream FATAL EMAXCONNSESSION.
        p_size = int(os.getenv("DB_POOL_SIZE", "10"))
        p_overflow = int(os.getenv("DB_MAX_OVERFLOW", "3"))
        p_timeout = int(os.getenv("DB_POOL_TIMEOUT", "60"))
    else:
        # Verified PostgreSQL max_connections is 60.
        # Across 2 workers (or replicas), 10 base + 5 overflow = 15 max per worker (30 total),
        # leaving 30 connections of headroom for Supabase internal services and superuser access.
        p_size = int(os.getenv("DB_POOL_SIZE", "10"))
        p_overflow = int(os.getenv("DB_MAX_OVERFLOW", "5"))
        p_timeout = int(os.getenv("DB_POOL_TIMEOUT", "45"))

    p_recycle = int(os.getenv("DB_POOL_RECYCLE", "300"))

    engine_kwargs.update({
        "pool_size": p_size,
        "max_overflow": p_overflow,
        "pool_timeout": p_timeout,
        "pool_recycle": p_recycle,  # Recycle every 5m to prevent stale sockets/leaks on Supabase
        "pool_pre_ping": True,
        "pool_use_lifo": True,  # Reuse most recently used connections first to allow idle overflow connections to close
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


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    connection_record.info["checkout_time"] = time.time()


@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    checkout_time = connection_record.info.pop("checkout_time", None)
    if checkout_time:
        duration = time.time() - checkout_time
        if duration > 5.0:
            logger.warning(
                f"LONG CONNECTION HOLD [{duration:.3f}s]: Database connection was checked out for >5s"
            )


def get_pool_status() -> dict:
    """Return runtime connection pool statistics for health & monitoring."""
    if is_sqlite or not hasattr(engine, "pool"):
        return {"status": "sqlite_or_no_pool"}
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checkedin": pool.checkedin(),
        "checkedout": pool.checkedout(),
        "overflow": pool.overflow(),
        "total_connections": pool.checkedin() + pool.checkedout(),
    }


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
        test_parameter, patient_test_result, cached_patient_registration
    )
    Base.metadata.create_all(bind=engine)
    if not is_sqlite:
        try:
            from datetime import datetime, timezone
            curr_yr = datetime.now(timezone.utc).year
            with engine.connect() as conn:
                conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS patient_seq_{curr_yr} START 1"))
                conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS patient_seq_{curr_yr + 1} START 1"))
                conn.commit()
        except Exception as e:
            logger.debug(f"Sequence pre-creation notice: {e}")
