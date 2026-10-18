"""Redis client — resilient connection management with automatic retry cooldown and fallback."""
import os
import sys
import time
import logging

_logger = logging.getLogger("akriti.redis")
_redis_client = None
_last_fail_time = 0.0
RECONNECT_COOLDOWN_SECONDS = 15.0

def get_redis():
    global _redis_client, _last_fail_time
    now = time.time()
    if _redis_client is not None:
        return _redis_client
    if (now - _last_fail_time) < RECONNECT_COOLDOWN_SECONDS:
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
        from backend.app.config import settings

        if not getattr(settings, "REDIS_ENABLED", True):
            return None

        # On Render without an external REDIS_URL, localhost:6379 does not exist.
        # Avoid hanging on connection attempts by defaulting directly to in-memory fallback.
        if os.getenv("RENDER") and settings.REDIS_URL in ("redis://localhost:6379/0", "redis://localhost:6379", ""):
            _last_fail_time = now + 86400  # Silence repeated attempts
            _logger.info("Render environment detected without external REDIS_URL configured; using in-memory fallback.")
            return None

        import redis
        kwargs = {
            "decode_responses": True,
            "socket_connect_timeout": 2.0,
            "socket_timeout": 2.0,
        }
        if settings.REDIS_URL.startswith("rediss://"):
            import ssl
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

        r = redis.from_url(settings.REDIS_URL, **kwargs)
        r.ping()
        _redis_client = r
        _last_fail_time = 0.0
        return r
    except Exception as e:
        _last_fail_time = now
        _logger.debug(f"Redis unavailable ({e}), retrying in {RECONNECT_COOLDOWN_SECONDS}s")
        return None

def reset_redis():
    """Reset cached client on runtime connection drops to trigger reconnect attempt on next cycle."""
    global _redis_client, _last_fail_time
    _redis_client = None
    _last_fail_time = time.time()

