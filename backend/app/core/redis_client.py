"""Redis client — resilient connection management with connection pooling, automatic retry cooldown and fallback."""
import os
import time
import logging
from typing import Optional

_logger = logging.getLogger("akriti.redis")
_redis_pool = None
_redis_client = None
_last_fail_time = 0.0
RECONNECT_COOLDOWN_SECONDS = 15.0


def get_redis():
    """
    Returns a thread-safe Redis client instance with connection pooling.
    If Redis is unavailable or disabled, returns None without raising unhandled exceptions.
    """
    global _redis_pool, _redis_client, _last_fail_time
    now = time.time()

    if _redis_client is not None:
        return _redis_client

    if (now - _last_fail_time) < RECONNECT_COOLDOWN_SECONDS:
        return None

    try:
        from backend.app.config import settings

        if not getattr(settings, "REDIS_ENABLED", True):
            return None

        redis_url = getattr(settings, "REDIS_URL", "")
        if not redis_url:
            return None

        # On Render without an external REDIS_URL, localhost:6379 does not exist.
        # Avoid hanging on connection attempts by defaulting directly to in-memory fallback.
        if os.getenv("RENDER") and redis_url in ("redis://localhost:6379/0", "redis://localhost:6379", ""):
            _last_fail_time = now + 86400  # Silence repeated attempts
            _logger.info("Render environment detected without external REDIS_URL configured; using in-memory fallback.")
            return None

        import redis

        kwargs = {
            "decode_responses": True,
            "socket_connect_timeout": 2.0,
            "socket_timeout": 2.0,
            "health_check_interval": 30,
            "max_connections": 20,
        }

        if redis_url.startswith("rediss://"):
            import ssl
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

        _redis_pool = redis.ConnectionPool.from_url(redis_url, **kwargs)
        r = redis.Redis(connection_pool=_redis_pool)
        r.ping()
        _redis_client = r
        _last_fail_time = 0.0
        return r
    except Exception as e:
        _last_fail_time = now
        _redis_client = None
        _redis_pool = None
        _logger.debug(f"Redis unavailable ({e}), retrying in {RECONNECT_COOLDOWN_SECONDS}s")
        return None


def reset_redis():
    """Reset cached client on runtime connection drops to trigger reconnect attempt on next cycle."""
    global _redis_pool, _redis_client, _last_fail_time
    try:
        if _redis_pool is not None:
            _redis_pool.disconnect()
    except Exception:
        pass
    _redis_pool = None
    _redis_client = None
    _last_fail_time = time.time()
