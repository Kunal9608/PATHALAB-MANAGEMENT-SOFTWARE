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
        import redis
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
        from backend.app.config import settings
        r = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5)
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
