from redis import Redis

from backend.app.core.config import setting

redis_client = Redis.from_url(setting.redis_url, decode_responses=True)
