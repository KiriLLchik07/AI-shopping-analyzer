from functools import lru_cache

import boto3

from backend.app.core.config import setting
from backend.app.storage.interface import ObjectStorage
from backend.app.storage.s3_storage import S3ObjectStorage


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    client = boto3.client(
        "s3",
        endpoint_url=setting.minio_url,
        aws_access_key_id=setting.minio_root_user,
        aws_secret_access_key=setting.minio_root_password,
        region_name=setting.minio_region,
    )

    return S3ObjectStorage(
        client=client,
        bucket=setting.minio_bucket,
    )
