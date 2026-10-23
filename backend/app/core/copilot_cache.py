"""
Copilot Cache Manager — Redis-first cache-aside with connection pooling,
graceful PostgreSQL fallback, versioned keys, and negative caching.
"""
import os
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
    "l1_hits": 0,
    "redis_hits": 0,
    "misses": 0,
    "negative_hits": 0,
    "writes": 0,
    "errors": 0,
    "invalidations": 0,
}

# L1 In-Memory Fast Cache (TTL-based) to safeguard against Redis latency or transient reconnects
_l1_cache: Dict[str, Any] = {}
_l1_max_size: int = 1000

def _get_l1(key: str) -> Optional[Any]:
    entry = _l1_cache.get(key)
    if entry is not None:
        exp, val = entry
        if time.time() < exp:
            return val
        _l1_cache.pop(key, None)
    return None

def _set_l1(key: str, val: Any, ttl: int):
    now = time.time()
    if len(_l1_cache) >= _l1_max_size:
        expired = [k for k, (exp, _) in _l1_cache.items() if now >= exp]
        for k in expired:
            _l1_cache.pop(k, None)
        if len(_l1_cache) >= _l1_max_size:
            oldest = sorted(_l1_cache.keys(), key=lambda k: _l1_cache[k][0])[:200]
            for k in oldest:
                _l1_cache.pop(k, None)
    _l1_cache[key] = (now + max(1, ttl), val)

def _invalidate_l1(prefix_or_sub: str):
    prefix = prefix_or_sub.rstrip("*")
    to_del = [k for k in _l1_cache.keys() if prefix in k]
    for k in to_del:
        _l1_cache.pop(k, None)


def _get_async_pool() -> Optional[aioredis.ConnectionPool]:
    global _async_pool
    if not getattr(settings, "REDIS_ENABLED", True):
        return None
    try:
        if os.getenv("RENDER") and settings.REDIS_URL in ("redis://localhost:6379/0", "redis://localhost:6379", ""):
            return None
        if _async_pool is None:
            kwargs = {
                "decode_responses": True,
                "max_connections": 20,
                "socket_connect_timeout": 2.0,
                "socket_timeout": 2.0,
            }
            if settings.REDIS_URL.startswith("rediss://"):
                import ssl
                verify_ssl = os.getenv("REDIS_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
                kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED if verify_ssl else ssl.CERT_NONE
                ca_certs = os.getenv("REDIS_SSL_CA_CERTS")
                if ca_certs and os.path.exists(ca_certs):
                    kwargs["ssl_ca_certs"] = ca_certs

            _async_pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                **kwargs
            )
    except Exception as e:
        logger.warning(f"Failed to create Redis connection pool: {e}")
        return None
    return _async_pool


def get_async_redis() -> Optional[aioredis.Redis]:
    global _async_redis_client, _redis_available, _last_error_log_time
    if not getattr(settings, "REDIS_ENABLED", True):
        return None
    try:
        pool = _get_async_pool()
        if pool is None:
            return None
        if _async_redis_client is None:
            _async_redis_client = aioredis.Redis(connection_pool=pool)
        return _async_redis_client
    except Exception as e:
        logger.warning(f"Failed to get async Redis client: {e}")
        return None


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
    """Fetch structured JSON from L1 memory or Redis. Returns None on cache miss."""
    # 1. Fast L1 Memory Cache (<0.05ms)
    l1_val = _get_l1(key)
    if l1_val is not None:
        cache_metrics["hits"] += 1
        cache_metrics["l1_hits"] += 1
        return l1_val

    # 2. Redis Cache (<2ms)
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
            cache_metrics["redis_hits"] += 1
            data = json.loads(val)
            # Store in L1 for instant sub-millisecond local repeat
            _set_l1(key, data, min(60, settings.REDIS_DEFAULT_TTL))
            logger.info(f"Redis Cache HIT for '{key.split(':')[2]}' [{latency:.2f}ms]")
            return data
        else:
            cache_metrics["misses"] += 1
            return None
    except (RedisError, Exception) as e:
        cache_metrics["errors"] += 1
        _log_redis_error("get", key, e)
        return None


async def set_cached(key: str, data: Any, ttl: Optional[int] = None) -> bool:
    """Store structured JSON in both L1 memory and Redis with specified TTL."""
    effective_ttl = ttl if ttl is not None else settings.REDIS_DEFAULT_TTL
    # Always write to L1 memory
    _set_l1(key, data, effective_ttl)

    client = get_async_redis()
    if client is None:
        cache_metrics["writes"] += 1
        return True

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
    if _get_l1(key) == "__NOT_FOUND__":
        cache_metrics["negative_hits"] += 1
        return True

    client = get_async_redis()
    if client is None:
        return False
    try:
        val = await client.get(key)
        if val is not None:
            cache_metrics["negative_hits"] += 1
            _set_l1(key, "__NOT_FOUND__", min(30, settings.REDIS_NEGATIVE_TTL))
            return True
        return False
    except Exception:
        return False


async def set_negative_cache(key: str, ttl: Optional[int] = None) -> bool:
    """Cache confirmed not-found status with a short TTL."""
    neg_ttl = ttl if ttl is not None else settings.REDIS_NEGATIVE_TTL
    _set_l1(key, "__NOT_FOUND__", neg_ttl)

    client = get_async_redis()
    if client is None:
        return True
    try:
        await client.set(key, "1", ex=neg_ttl)
        return True
    except Exception:
        return False


# ── Invalidation (Async & Sync) ────────────────────────────────────────────────

async def async_invalidate_patient(patient_code: str):
    """Invalidate patient cache entries upon registration, update, payment, or report."""
    norm_code = patient_code.strip().upper()
    _invalidate_l1(f"copilot:{KEY_VERSION}:patient:{norm_code}")
    _invalidate_l1(f"copilot:{KEY_VERSION}:patient_not_found:{norm_code}")
    _invalidate_l1(f"copilot:{KEY_VERSION}:pending_reports")
    _invalidate_l1(f"copilot:{KEY_VERSION}:latest_reports")
    _invalidate_l1(f"copilot:{KEY_VERSION}:finance")

    client = get_async_redis()
    if client is None:
        return
    try:
        keys_to_del = [
            patient_not_found_key(norm_code),
            patient_key(norm_code, "all"),
        ]
        # Also delete pattern keys if staff-scoped
        for pat in [
            f"copilot:{KEY_VERSION}:patient:{norm_code}:*",
            f"copilot:{KEY_VERSION}:pending_reports:*",
            f"copilot:{KEY_VERSION}:latest_reports:*",
            f"copilot:{KEY_VERSION}:finance:*",
        ]:
            keys = await client.keys(pat)
            if keys:
                keys_to_del.extend([k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in keys])

        if keys_to_del:
            await client.delete(*set(keys_to_del))
            cache_metrics["invalidations"] += len(keys_to_del)
            logger.info(f"Invalidated {len(keys_to_del)} copilot cache entries for patient {norm_code}")
    except Exception as e:
        logger.warning(f"Error invalidating patient cache: {e}")


def invalidate_patient_sync(patient_code: str):
    """Synchronous cache invalidation helper for sync endpoints and background tasks."""
    norm_code = patient_code.strip().upper()
    _invalidate_l1(f"copilot:{KEY_VERSION}:patient:{norm_code}")
    _invalidate_l1(f"copilot:{KEY_VERSION}:patient_not_found:{norm_code}")
    _invalidate_l1(f"copilot:{KEY_VERSION}:pending_reports")
    _invalidate_l1(f"copilot:{KEY_VERSION}:latest_reports")
    _invalidate_l1(f"copilot:{KEY_VERSION}:finance")

    from backend.app.core.redis_client import get_redis
    r = get_redis()
    if not r:
        return
    try:
        keys_to_del: list[str] = [patient_not_found_key(norm_code), patient_key(norm_code, "all")]
        for pattern in [
            f"copilot:{KEY_VERSION}:patient:{norm_code}:*",
            f"copilot:{KEY_VERSION}:pending_reports:*",
            f"copilot:{KEY_VERSION}:latest_reports:*",
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
