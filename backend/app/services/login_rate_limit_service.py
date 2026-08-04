import hashlib

from backend.app.core.config import setting
from backend.app.db.redis_client import redis_client

def _failure_key(email: str, ip: str) -> str:
    identity = f"{email}:{ip}"
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()
    return f"auth:login:failures:{identity_hash}"

def get_retry_after(email: str, ip: str) -> int | None:
    key = _failure_key(email, ip)
    attempts = redis_client.get(key)

    if attempts is None or int(attempts) < setting.login_rate_limit_attempts:
        return None

    ttl = redis_client.ttl(key)
    return ttl if ttl > 0 else None

def record_failure(email: str, ip: str) -> int:
    key = _failure_key(email, ip)
    with redis_client.pipeline(transaction=True) as pipeline:
        pipeline.incr(key)
        pipeline.expire(key, setting.login_rate_limit_window_seconds, nx=True)
        attempts, _ = pipeline.execute()

    return int(attempts)

def reset_failures(email: str, ip: str) -> None:
    redis_client.delete(_failure_key(email, ip))
