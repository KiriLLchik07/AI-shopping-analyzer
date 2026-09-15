from typing import Any, BinaryIO

from botocore.exceptions import BotoCoreError, ClientError

from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.interface import ObjectStorage


class S3ObjectStorage(ObjectStorage):
    def __init__(
        self, client: Any, bucket: str, download_client: Any | None = None
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.download_client = (
            download_client if download_client is not None else client
        )

    def upload(self, object_key: str, file: BinaryIO, content_type: str) -> None:
        try:
            self.client.upload_fileobj(
                file, self.bucket, object_key, ExtraArgs={"ContentType": content_type}
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Failed to upload object") from error

    def delete(self, object_key: str) -> None:
        try:
            self.client.delete_object(
                Bucket=self.bucket,
                Key=object_key,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Failed to delete object") from error

    def generate_download_url(self, object_key: str, expires_seconds: int) -> str:
        try:
            return self.download_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": object_key,
                    "ResponseContentDisposition": "inline",
                    "ResponseCacheControl": "private, no-store",
                },
                ExpiresIn=expires_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Failed to generate download URL") from error

    def is_available(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False
