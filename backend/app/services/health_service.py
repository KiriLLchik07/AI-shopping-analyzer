from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import setting
from backend.app.db.session import engine
from backend.app.storage.interface import ObjectStorage


class HealthService:
    def __init__(self, object_storage: ObjectStorage) -> None:
        self.object_storage = object_storage
        self.redis_client = Redis.from_url(setting.redis_url)

    def check_ready(self) -> dict[str, bool]:
        checks = {
            "postgresql": self._check_postgres(),
            "minio": self._check_minio(),
            "redis": self._check_redis(),
        }
        return checks

    def _check_postgres(self) -> bool:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def _check_minio(self) -> bool:
        return self.object_storage.is_available()

    def _check_redis(self) -> bool:
        try:
            return self.redis_client.ping()
        except RedisError:
            return False
