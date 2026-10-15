"""
Copilot Cache Manager — Redis-first cache-aside with connection pooling,
graceful PostgreSQL fallback, versioned keys, and negative caching.
"""
import json
import logging
import time
from typing import Optional, Any, Dict
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from backend.app.config import settings

logger = logging.getLogger("akriti.copilot.cache")

# Shared connection pool
_async_pool: Optional[aioredis.ConnectionPool] = None
_async_redis_client: Optional[aioredis.Redis] = None
_redis_available: bool = True
_last_error_log_time: float = 0.0

# In-memory metrics tracking (thread-safe counters)
cache_metrics = {
    "hits": 0,
    "misses": 0,
    "negative_hits": 0,
    "writes": 0,
    "errors": 0,
    "invalidations": 0,
}


def _get_async_pool() -> Optional[aioredis.ConnectionPool]:
    global _async_pool
    if not settings.REDIS_ENABLED:
        return None
    if _async_pool is None:
        try:
            _async_pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=0.5,
                socket_timeout=1.0,
            )
        except Exception as e:
            logger.warning(f"Failed to create Redis connection pool: {e}")
            return None
    return _async_pool


def get_async_redis() -> Optional[aioredis.Redis]:
    global _async_redis_client, _redis_available, _last_error_log_time
    if not settings.REDIS_ENABLED:
        return None
    pool = _get_async_pool()
    if pool is None:
        return None
    if _async_redis_client is None:
        _async_redis_client = aioredis.Redis(connection_pool=pool)
    return _async_redis_client


# ── Key Generators ─────────────────────────────────────────────────────────────
KEY_VERSION = "v1"

def patient_key(patient_code: str, scope: str = "all") -> str:
    norm_code = patient_code.strip().upper()
    return f"copilot:{KEY_VERSION}:patient:{norm_code}:{scope}"

def patient_not_found_key(patient_code: str) -> str:
    norm_code = patient_code.strip().upper()
    return f"copilot:{KEY_VERSION}:patient_not_found:{norm_code}"

def phone_key(phone: str, scope: str = "all") -> str:
    return f"copilot:{KEY_VERSION}:phone:{phone.strip()}:{scope}"

def test_key(test_code: str) -> str:
    return f"copilot:{KEY_VERSION}:test:{test_code.strip().upper()}"

def finance_key(date_str: str, scope: str = "all") -> str:
    return f"copilot:{KEY_VERSION}:finance:{date_str}:{scope}"

def pending_reports_key(scope: str = "all") -> str:
    return f"copilot:{KEY_VERSION}:pending_reports:{scope}"

def audit_logs_key() -> str:
    return f"copilot:{KEY_VERSION}:audit_logs:admin"


# ── Cache Operations (Async) ───────────────────────────────────────────────────

async def get_cached(key: str) -> Optional[Dict[str, Any]]:
    """Fetch structured JSON from Redis. Returns None on cache miss or Redis failure."""
    client = get_async_redis()
    if client is None:
        cache_metrics["misses"] += 1
        return None

    t0 = time.time()
    try:
        val = await client.get(key)
        latency = (time.time() - t0) * 1000
        if val is not None:
            cache_metrics["hits"] += 1
            logger.debug(f"Redis Cache HIT for key prefix '{key.split(':')[2]}' [{latency:.2f}ms]")
            return json.loads(val)
        else:
            cache_metrics["misses"] += 1
            return None
    except (RedisError, Exception) as e:
        cache_metrics["errors"] += 1
        _log_redis_error("get", key, e)
        return None


async def set_cached(key: str, data: Any, ttl: Optional[int] = None) -> bool:
    """Store structured JSON in Redis with specified TTL."""
    client = get_async_redis()
    if client is None:
        return False

    effective_ttl = ttl if ttl is not None else settings.REDIS_DEFAULT_TTL
    try:
        serialized = json.dumps(data, default=str)
        await client.set(key, serialized, ex=effective_ttl)
        cache_metrics["writes"] += 1
        return True
    except (RedisError, Exception) as e:
        cache_metrics["errors"] += 1
        _log_redis_error("set", key, e)
        return False


async def get_negative_cache(key: str) -> bool:
    """Check if record is confirmed non-existent in negative cache."""
    client = get_async_redis()
    if client is None:
        return False
    try:
        val = await client.get(key)
        if val is not None:
            cache_metrics["negative_hits"] += 1
            return True
        return False
    except Exception:
        return False


async def set_negative_cache(key: str, ttl: Optional[int] = None) -> bool:
    """Cache confirmed not-found status with a short TTL."""
    client = get_async_redis()
    if client is None:
        return False
    neg_ttl = ttl if ttl is not None else settings.REDIS_NEGATIVE_TTL
    try:
        await client.set(key, "1", ex=neg_ttl)
        return True
    except Exception:
        return False


# ── Invalidation (Async & Sync) ────────────────────────────────────────────────

async def async_invalidate_patient(patient_code: str):
    """Invalidate patient cache entries upon registration, update, payment, or report."""
    client = get_async_redis()
    if client is None:
        return
    norm_code = patient_code.strip().upper()
    try:
        keys_to_del = [
            patient_not_found_key(norm_code),
            patient_key(norm_code, "all"),
        ]
        # Also delete pattern keys if staff-scoped
        pattern = f"copilot:{KEY_VERSION}:patient:{norm_code}:*"
        keys = await client.keys(pattern)
        if keys:
            keys_to_del.extend([k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in keys])

        # Invalidate pending reports & finance
        pending_keys = await client.keys(f"copilot:{KEY_VERSION}:pending_reports:*")
        if pending_keys:
            keys_to_del.extend([k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in pending_keys])

        finance_keys = await client.keys(f"copilot:{KEY_VERSION}:finance:*")
        if finance_keys:
            keys_to_del.extend([k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in finance_keys])

        if keys_to_del:
            await client.delete(*set(keys_to_del))
            cache_metrics["invalidations"] += len(keys_to_del)
            logger.info(f"Invalidated {len(keys_to_del)} copilot cache entries for patient {norm_code}")
    except Exception as e:
        logger.warning(f"Error invalidating patient cache: {e}")


def invalidate_patient_sync(patient_code: str):
    """Synchronous cache invalidation helper for sync endpoints and background tasks."""
    from backend.app.core.redis_client import get_redis
    r = get_redis()
    if not r:
        return
    norm_code = patient_code.strip().upper()
    try:
        keys_to_del: list[str] = [patient_not_found_key(norm_code), patient_key(norm_code, "all")]
        for pattern in [
            f"copilot:{KEY_VERSION}:patient:{norm_code}:*",
            f"copilot:{KEY_VERSION}:pending_reports:*",
            f"copilot:{KEY_VERSION}:finance:*",
        ]:
            try:
                matched = r.keys(pattern)
                if matched:
                    keys_to_del.extend([k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in matched])
            except Exception:
                pass
        if keys_to_del:
            r.delete(*set(keys_to_del))
            cache_metrics["invalidations"] += len(keys_to_del)
    except Exception as e:
        logger.warning(f"Sync cache invalidation error: {e}")


async def async_invalidate_test(test_code: Optional[str] = None):
    """Invalidate test catalog cache asynchronously."""
    client = get_async_redis()
    if client is None:
        return
    try:
        if test_code:
            await client.delete(test_key(test_code))
        else:
            pattern = f"copilot:{KEY_VERSION}:test:*"
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
        cache_metrics["invalidations"] += 1
    except Exception as e:
        logger.warning(f"Error invalidating test cache: {e}")


def invalidate_test_sync(test_code: Optional[str] = None):
    """Synchronous test catalog cache invalidation helper."""
    from backend.app.core.redis_client import get_redis
    r = get_redis()
    if not r:
        return
    try:
        if test_code:
            r.delete(test_key(test_code))
        else:
            keys = r.keys(f"copilot:{KEY_VERSION}:test:*")
            if keys:
                r.delete(*keys)
    except Exception as e:
        logger.warning(f"Sync test cache invalidation error: {e}")


# Aliases for consistent naming
invalidate_patient_async = async_invalidate_patient
invalidate_test_async = async_invalidate_test


def _log_redis_error(operation: str, key: str, err: Exception):
    global _last_error_log_time
    now = time.time()
    # Rate-limit Redis error log to at most once every 10 seconds to avoid log spam
    if now - _last_error_log_time > 10.0:
        _last_error_log_time = now
        logger.warning(f"Redis {operation} failed for key '{key[:40]}': {err} — falling back safely to PostgreSQL.")
