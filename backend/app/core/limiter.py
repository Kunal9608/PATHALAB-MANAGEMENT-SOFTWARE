from slowapi import Limiter
from backend.app.dependencies import get_client_ip
import os

redis_url = os.getenv("REDIS_URL")
redis_enabled = os.getenv("REDIS_ENABLED", "true").lower() in ("true", "1", "yes")
use_redis = False

if redis_enabled and redis_url and not (os.getenv("RENDER") and redis_url in ("redis://localhost:6379/0", "redis://localhost:6379", "")):
    try:
        import redis
        kwargs = {"socket_connect_timeout": 1.5}
        if redis_url.startswith("rediss://"):
            import ssl
            verify_ssl = os.getenv("REDIS_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
            kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED if verify_ssl else ssl.CERT_NONE
            ca_certs = os.getenv("REDIS_SSL_CA_CERTS")
            if ca_certs and os.path.exists(ca_certs):
                kwargs["ssl_ca_certs"] = ca_certs
        r = redis.from_url(redis_url, **kwargs)
        r.ping()
        use_redis = True
    except Exception:
        pass

if use_redis:
    limiter = Limiter(key_func=get_client_ip, storage_uri=redis_url)
else:
    limiter = Limiter(key_func=get_client_ip)

