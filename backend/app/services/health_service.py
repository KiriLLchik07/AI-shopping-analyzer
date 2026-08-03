import boto3
from redis import Redis
from sqlalchemy import text

from backend.app.core.config import setting
from backend.app.db.session import engine

class HealthService:
    def __init__(self):
        self.minio_client = boto3.client(
            "s3",
            endpoint_url=setting.minio_url,
            aws_access_key_id=setting.minio_root_user,
            aws_secret_access_key=setting.minio_root_password,
            region_name=setting.minio_region
        )
        self.redis_client = Redis.from_url(
            setting.redis_url
        )

    def check_ready(self) -> dict[str, bool]:
        checks = {
            "postgresql": self._check_postgres(),
            "minio": self._check_minio(),
            "redis": self._check_redis()
        }
        return checks

    def _check_postgres(self) -> bool:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _check_minio(self) -> bool:
        try:
            self.minio_client.head_bucket(Bucket=setting.minio_bucket)
            return True
        except Exception:
            return False

    def _check_redis(self) -> bool:
        try:
            return self.redis_client.ping()
        except Exception:
            return False

