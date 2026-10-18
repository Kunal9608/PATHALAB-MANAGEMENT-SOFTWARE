"""Idempotency service — Redis-backed at-most-once execution with automatic in-memory fallback."""
import json
import time
import threading
import logging
from typing import Callable, Any, Optional
from fastapi import HTTPException

from backend.app.core.redis_client import get_redis, reset_redis

logger = logging.getLogger("akriti.idempotency")

# In-memory fallback cache: key -> (expire_at, value)
_mem_cache: dict[str, tuple[float, Any]] = {}
_mem_lock = threading.Lock()
_MAX_MEM_ENTRIES = 5000


def _prune_expired_mem_cache(now: float):
    if len(_mem_cache) > _MAX_MEM_ENTRIES:
        expired_keys = [k for k, (exp, _) in _mem_cache.items() if exp < now]
        for k in expired_keys:
            _mem_cache.pop(k, None)
        if len(_mem_cache) > _MAX_MEM_ENTRIES:
            sorted_keys = sorted(_mem_cache.keys(), key=lambda k: _mem_cache[k][0])
            for k in sorted_keys[: len(sorted_keys) // 5]:
                _mem_cache.pop(k, None)


def with_idempotency(key: str, user_id: str, handler_fn: Callable, ttl: int = 86400) -> Any:
    """
    If we've seen this key before, return the stored response verbatim.
    Otherwise, execute handler_fn(), store result, and return it.
    Uses Redis when available, with automatic in-memory fallback when Redis is absent or offline.
    """
    redis_key = f"idem:{key}:{user_id}"

    # 1. Try Redis first if available
    redis = get_redis()
    if redis:
        try:
            cached = redis.get(redis_key)
            if cached:
                if cached in ("PENDING", b"PENDING"):
                    raise HTTPException(status_code=409, detail="Duplicate request is already processing.")
                try:
                    return json.loads(cached)
                except Exception:
                    return cached

            # Try to acquire lock
            acquired = redis.set(redis_key, "PENDING", nx=True, ex=30)
            if not acquired:
                raise HTTPException(status_code=409, detail="Duplicate request is already processing.")

            # Execute the actual business logic
            try:
                result = handler_fn()
            except Exception:
                try:
                    redis.delete(redis_key)
                except Exception:
                    pass
                raise

            # Serialize and store
            try:
                serialized = json.dumps(result, default=str)
                redis.set(redis_key, serialized, ex=ttl)
            except Exception:
                pass  # Non-fatal — operation succeeded even if caching fails

            # Mirror into in-memory cache as well
            now = time.time()
            with _mem_lock:
                _mem_cache[redis_key] = (now + ttl, result)

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Redis idempotency error ({e}); seamlessly falling back to in-memory: {redis_key}")
            reset_redis()
            # Fall through to in-memory fallback below

    # 2. In-memory fallback (used when Redis is not deployed or temporarily down)
    now = time.time()
    with _mem_lock:
        _prune_expired_mem_cache(now)
        entry = _mem_cache.get(redis_key)
        if entry:
            exp, cached_val = entry
            if exp > now:
                if cached_val == "PENDING":
                    raise HTTPException(status_code=409, detail="Duplicate request is already processing.")
                return cached_val
            else:
                _mem_cache.pop(redis_key, None)

        # Acquire lock
        _mem_cache[redis_key] = (now + 30.0, "PENDING")

    try:
        result = handler_fn()
    except Exception:
        with _mem_lock:
            _mem_cache.pop(redis_key, None)
        raise

    with _mem_lock:
        _mem_cache[redis_key] = (now + ttl, result)

    return result


def check_key_exists(key: str, user_id: str) -> Optional[Any]:
    """Returns stored result if key exists, else None. Safe fallback to in-memory."""
    redis_key = f"idem:{key}:{user_id}"
    redis = get_redis()
    if redis:
        try:
            cached = redis.get(redis_key)
            if cached and cached not in ("PENDING", b"PENDING"):
                try:
                    return json.loads(cached)
                except Exception:
                    return cached
        except Exception as e:
            logger.warning(f"Redis check_key_exists error ({e}): {redis_key}")
            reset_redis()

    now = time.time()
    with _mem_lock:
        entry = _mem_cache.get(redis_key)
        if entry:
            exp, cached_val = entry
            if exp > now and cached_val != "PENDING":
                return cached_val
            elif exp <= now:
                _mem_cache.pop(redis_key, None)
    return None


def store_result(key: str, user_id: str, result: Any, ttl: int = 86400):
    """Store result in cache (Redis + in-memory fallback)."""
    redis_key = f"idem:{key}:{user_id}"
    redis = get_redis()
    if redis:
        try:
            serialized = json.dumps(result, default=str)
            redis.set(redis_key, serialized, ex=ttl)
        except Exception as e:
            logger.warning(f"Redis store_result error ({e}): {redis_key}")
            reset_redis()

    now = time.time()
    with _mem_lock:
        _prune_expired_mem_cache(now)
        _mem_cache[redis_key] = (now + ttl, result)

