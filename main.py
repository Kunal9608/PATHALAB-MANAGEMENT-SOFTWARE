"""
Akriti Diagnostics Center — Lab Management System
Single entry point: python main.py

This file:
  1. Runs startup checks (DB, Redis connectivity)
  2. Applies pending Alembic migrations (if configured)
  3. Starts Uvicorn serving both the FastAPI API and the static frontend
"""

import os
import sys
import subprocess
from pathlib import Path

# Ensure the project root is on Python path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

def check_env():
    """Verify critical environment variables are set."""
    required = ["DATABASE_URL", "JWT_SECRET_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"\n[ERROR] Missing required environment variables: {', '.join(missing)}")
        print("  -> Copy .env.example to .env and fill in the values.")
        print("  -> Then run: python main.py\n")
        sys.exit(1)

    env = os.getenv("ENVIRONMENT", "development").lower()
    if env == "production":
        jwt_key = (os.getenv("JWT_SECRET_KEY") or "").strip()
        insecure_placeholders = {
            "change-this-secret",
            "secret",
            "jwt-secret",
            "your-secret-key",
            "your-secret",
            "generate_your_64_char_secure_random_string_here",
            "password",
            "admin",
            "12345678",
            "default",
        }
        if jwt_key.lower() in insecure_placeholders or len(jwt_key) < 32 or len(set(jwt_key)) < 10:
            print("\n[ERROR] Insecure, short, or low-entropy JWT_SECRET_KEY in production.")
            print("  -> Production requires at least 32 cryptographically secure random characters.")
            print("  -> Run: python backend/scripts/generate_secrets.py to generate a secure key.\n")
            sys.exit(1)

def check_database():
    """Test PostgreSQL connectivity."""
    try:
        import sqlalchemy as sa
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("  [WARN] DATABASE_URL is not set")
            return False
        if db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if "supabase" in db_url and "sslmode" not in db_url:
            separator = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{separator}sslmode=require"
        engine = sa.create_engine(db_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            print("  [OK] Database connected")
            return True
        finally:
            engine.dispose()
    except Exception as e:
        print(f"  [WARN] Database not reachable: {e}")
        print("  -> Make sure PostgreSQL is running and DATABASE_URL is correct in .env")
        return False

def check_redis():
    """Test Redis connectivity."""
    try:
        if not os.getenv("REDIS_ENABLED", "true").lower() in ("true", "1", "yes"):
            print("  [OK] Redis disabled in configuration (In-Memory Fallback Mode)")
            return True
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        if os.getenv("RENDER") and redis_url in ("redis://localhost:6379/0", "redis://localhost:6379", ""):
            print("  [OK] Redis not configured on Render (In-Memory Fallback Mode)")
            return True
        import redis as redis_lib
        kwargs = {"socket_connect_timeout": 1.5}
        if redis_url.startswith("rediss://"):
            import ssl
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
        r = redis_lib.from_url(redis_url, **kwargs)
        r.ping()
        print("  [OK] Redis connected")
        return True
    except Exception as e:
        print(f"  [OK] Redis connected (In-Memory Fallback Mode: {e})")
        return True

def run_migrations():
    """Apply pending Alembic migrations."""
    try:
        alembic_ini = ROOT / "alembic.ini"
        if not alembic_ini.exists():
            print("  [SKIP] No alembic.ini found — skipping migrations")
            return
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  [OK] Database migrations up to date")
        else:
            print(f"  [WARN] Migration issue: {result.stderr[-200:]}")
    except Exception as e:
        print(f"  [WARN] Could not run migrations: {e}")

def start_whatsapp_microservice():
    """Starts internal Node.js WhatsApp microservice if enabled and not already running."""
    if os.getenv("WHATSAPP_ENABLED", "true").lower() == "false":
        print("  [SKIP] WhatsApp microservice disabled in configuration")
        return

    # Skip internal node if explicitly disabled or pointing to a separate container
    wa_url = os.getenv("WHATSAPP_SERVICE_URL", "")
    start_internal = os.getenv("START_INTERNAL_WHATSAPP", "").lower()
    if start_internal == "false" or (wa_url and "whatsapp:3001" in wa_url):
        print(f"  [OK] External WhatsApp microservice configured ({wa_url or 'external'}) — skipping local Node process")
        return

    whatsapp_dir = ROOT / "WHATSAPP" / "service"
    server_script = whatsapp_dir / "src" / "server.js"
    if not server_script.exists():
        return

    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", 3001)) == 0:
                print("  [OK] WhatsApp microservice is already running on port 3001")
                return
    except Exception:
        pass

    import shutil
    node_bin = shutil.which("node")
    if not node_bin:
        print("  [WARN] Node.js not found in PATH — WhatsApp microservice cannot auto-start")
        return

    try:
        proc = subprocess.Popen(
            [node_bin, str(server_script)],
            cwd=str(ROOT)
        )
        import atexit
        atexit.register(lambda: proc.terminate() if proc.poll() is None else None)
        print(f"  [OK] WhatsApp microservice started in background (PID: {proc.pid}) on port 3001")
    except Exception as e:
        print(f"  [WARN] Could not auto-start WhatsApp microservice: {e}")

def main():
    print("\n" + "="*60)
    print("  Akriti Diagnostics Center — Lab Management System")
    print("="*60)
    print("\nRunning startup checks...\n")

    check_env()
    db_ok = check_database()
    redis_ok = check_redis()
    start_whatsapp_microservice()

    if db_ok:
        run_migrations()

        try:
            from backend.seed.seed import seed
            seed()
        except Exception as e:
            print(f"  [WARN] Auto-seeding database failed: {e}")

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    env = os.getenv("ENVIRONMENT", "development")
    reload = env == "development"
    workers = int(os.getenv("WORKERS", "1")) if not reload else 1

    print(f"\n{'='*60}")
    print(f"  Starting server...")
    print(f"  Environment : {env.upper()}")
    print(f"  URL         : http://{'localhost' if host == '0.0.0.0' else host}:{port}")
    print(f"  API Docs    : http://{'localhost' if host == '0.0.0.0' else host}:{port}/docs")
    print(f"  Hot reload  : {'yes (development)' if reload else 'no (production)'}")
    if not reload:
        print(f"  Workers     : {workers}")
    print(f"{'='*60}\n")

    import uvicorn
    os.environ["PYTHONUNBUFFERED"] = "1"
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level="info",
        access_log=True,
        server_header=False,
    )


if __name__ == "__main__":
    main()
