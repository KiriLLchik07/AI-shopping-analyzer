from functools import lru_cache

import boto3
from botocore.config import Config

from backend.app.core.config import setting
from backend.app.storage.interface import ObjectStorage
from backend.app.storage.s3_storage import S3ObjectStorage


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )

    client = boto3.client(
        "s3",
        endpoint_url=setting.minio_url,
        aws_access_key_id=setting.minio_root_user,
        aws_secret_access_key=setting.minio_root_password,
        region_name=setting.minio_region,
        config=config,
    )

    download_client = boto3.client(
        "s3",
        endpoint_url=setting.minio_public_url,
        aws_access_key_id=setting.minio_root_user,
        aws_secret_access_key=setting.minio_root_password,
        region_name=setting.minio_region,
        config=config,
    )

    return S3ObjectStorage(
        client=client,
        bucket=setting.minio_bucket,
        download_client=download_client,
    )
