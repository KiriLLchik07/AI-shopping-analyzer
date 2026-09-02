from typing import BinaryIO, Protocol


class ObjectStorage(Protocol):
    def upload(self, object_key: str, file: BinaryIO, content_type: str) -> None:
        pass

    def delete(self, object_key: str) -> None:
        pass

    def generate_download_url(self, object_key: str, expires_seconds: int) -> str:
        pass

    def is_available(self) -> bool:
        pass
