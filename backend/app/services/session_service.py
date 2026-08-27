import hashlib
import secrets
from uuid import UUID
from backend.app.core.config import setting
from backend.app.db.redis_client import redis_client


def _session_key(session_id: str) -> str:
    session_hash = hashlib.sha256(session_id.encode()).hexdigest()
    return f"auth_session:{session_hash}"


def _user_sessions_key(user_id: UUID | str) -> str:
    return f"auth_user_sessions:{user_id}"


def create_session(user_id: UUID) -> str:
    session_id = secrets.token_urlsafe(32)
    session_key = _session_key(session_id)
    user_session_key = _user_sessions_key(user_id)

    with redis_client.pipeline(transaction=True) as pipeline:
        pipeline.set(session_key, str(user_id), ex=setting.session_ttl_seconds)
        pipeline.sadd(user_session_key, session_key)
        pipeline.expire(user_session_key, setting.session_ttl_seconds)
        pipeline.execute()

    return session_id


def get_session_user_id(session_id: str) -> UUID | None:
    user_id = redis_client.get(_session_key(session_id))
    return UUID(user_id) if user_id else None


def delete_session(session_id: str) -> None:
    session_key = _session_key(session_id)
    user_id = redis_client.get(session_key)

    with redis_client.pipeline(transaction=True) as pipeline:
        pipeline.delete(session_key)

        if user_id is not None:
            pipeline.srem(_user_sessions_key(user_id), session_key)

        pipeline.execute()


def delete_all_user_sessions(user_id: UUID) -> None:
    user_sessions_key = _user_sessions_key(user_id)
    session_keys = redis_client.smembers(user_sessions_key)

    with redis_client.pipeline(transaction=True) as pipeline:
        if session_keys:
            pipeline.delete(*session_keys)

        pipeline.delete(user_sessions_key)
        pipeline.execute()
