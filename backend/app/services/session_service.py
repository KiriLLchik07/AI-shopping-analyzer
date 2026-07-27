import hashlib
import secrets
from uuid import UUID
from redis import Redis
from backend.app.core.config import setting

redis_client = Redis.from_url(setting.redis_url, decode_responses=True)

def _session_key(session_id: str) -> str:
    session_hash = hashlib.sha256(session_id.encode()).hexdigest()
    return f"auth_session:{session_hash}"

def create_session(user_id: UUID) -> str:
    session_id = secrets.token_urlsafe(32)
    redis_client.set(_session_key(session_id), str(user_id), ex=setting.session_ttl_seconds)
    return session_id

def get_session_user_id(session_id: str) -> UUID | None:
    user_id = redis_client.get(_session_key(session_id))
    return UUID(user_id) if user_id else None

def delete_session(session_id: str) -> None:
    redis_client.delete(_session_key(session_id))
