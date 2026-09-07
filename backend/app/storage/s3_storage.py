from typing import Any, BinaryIO

from botocore.exceptions import BotoCoreError, ClientError

from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.interface import ObjectStorage


class S3ObjectStorage(ObjectStorage):
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

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
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=expires_seconds,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Failed to generate download URL") from error

    def is_available(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False
