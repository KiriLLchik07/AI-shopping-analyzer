import logging
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import image_settings
from backend.app.core.exceptions import (
    InvalidReceiptImageError,
    ReceiptUploadUnavailableError,
    UploadTooLargeError,
)
from backend.app.models.object_cleanup_task import ObjectCleanupTask
from backend.app.models.receipt import Receipt
from backend.app.repositories.receipt_repository import ReceiptRepository
from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.interface import ObjectStorage

logger = logging.getLogger(__name__)


class ReceiptUploadService:
    def __init__(
        self,
        db_session: Session,
        object_storage: ObjectStorage,
        cleanup_session_factory: sessionmaker[Session],
    ) -> None:
        self.db_session = db_session
        self.object_storage = object_storage
        self.repository = ReceiptRepository(db_session)
        self.cleanup_session_factory = cleanup_session_factory

    def upload(
        self,
        user_id: UUID,
        file: BinaryIO,
    ) -> Receipt:
        data = self._read_file(file)
        extension, content_type = self._validate_image(data)

        receipt_id = uuid4()
        object_key = f"users/{user_id}/receipts/{receipt_id}/original.{extension}"

        try:
            self._registry_cleanup_task(receipt_id=receipt_id, object_key=object_key)
        except SQLAlchemyError as error:
            self._rollback()
            logger.exception(
                "Failed to register cleanup task for receipt %s",
                receipt_id,
            )

            raise ReceiptUploadUnavailableError() from error

        try:
            receipt = self.repository.create_receipt(
                receipt_id=receipt_id,
                user_id=user_id,
                image_object_key=object_key,
            )
            with BytesIO(data) as stream:
                self.object_storage.upload(
                    object_key=object_key, file=stream, content_type=content_type
                )

            self.db_session.execute(
                delete(ObjectCleanupTask).where(
                    ObjectCleanupTask.receipt_id == receipt_id
                )
            )

            self.db_session.commit()

        except ObjectStorageError as error:
            self._rollback()

            logger.exception(
                "Storage upload failed for receipt %s; cleanup task retained",
                receipt_id,
            )
            raise ReceiptUploadUnavailableError() from error

        except SQLAlchemyError as error:
            self._rollback()

            logger.exception(
                "Database operation failed for receipt %s; "
                "object %s will be reconciled if task remains",
                receipt_id,
                object_key,
            )
            raise ReceiptUploadUnavailableError() from error

        return receipt

    @staticmethod
    def _read_file(file: BinaryIO) -> bytes:
        file.seek(0)

        data = file.read(image_settings.max_upload_bytes + 1)

        if not data:
            raise InvalidReceiptImageError("Image must not be empty")

        if len(data) > image_settings.max_upload_bytes:
            raise UploadTooLargeError(
                f"Image must not exceed {image_settings.max_upload_bytes} bytes"
            )

        return data

    @staticmethod
    def _validate_image(data: bytes) -> tuple[str, str]:
        try:
            with Image.open(BytesIO(data)) as image:
                image_format = image.format

                if image_format not in image_settings.formats:
                    raise InvalidReceiptImageError(
                        "Supported image formats: " + ", ".join(image_settings.formats)
                    )

                if image.width * image.height > image_settings.max_pixels:
                    raise InvalidReceiptImageError(
                        f"Image must not exceed {image_settings.max_pixels} pixels"
                    )

                if getattr(image, "n_frames", 1) != 1:
                    raise InvalidReceiptImageError(
                        "Animated and multi-frame images are not supported"
                    )

                image.verify()

            with Image.open(BytesIO(data)) as image:
                image.load()

        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
            Image.DecompressionBombError,
        ) as error:
            raise InvalidReceiptImageError(
                "File is not a valid image or is corrupted"
            ) from error

        return image_settings.formats[image_format]

    def _rollback(self) -> None:
        try:
            self.db_session.rollback()
        except SQLAlchemyError:
            logger.exception("Failed to roll back receipt transaction")

    def _delete_object(self, object_key: str) -> None:
        try:
            self.object_storage.delete(object_key)
        except ObjectStorageError:
            logger.exception("Failed to clean up receipt image %s", object_key)

    def _registry_cleanup_task(self, receipt_id: UUID, object_key: str) -> None:
        with self.cleanup_session_factory.begin() as session:
            session.add(ObjectCleanupTask(receipt_id=receipt_id, object_key=object_key))
