from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.exceptions import (
    ConflictError,
    ReceiptNotFoundError,
    ReceiptProcessingConflictError,
)
from backend.app.core.receipt_processing_errors import get_safe_processing_error
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.receipt_processing_repository import (
    ReceiptProcessingRepository,
)
from backend.app.schemas.processing import (
    ReceiptProcessingInput,
    ReceiptProcessingResult,
    ReceiptProcessTicket,
)


class SaveProcessingOutcome(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    RECEIPT_DELETED = "receipt_deleted"
    STALE_JOB = "stale_job"


class ReceiptProcessingService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def prepare_process(
        self, receipt_id: UUID, user_id: UUID, replace_items: bool
    ) -> ReceiptProcessTicket:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id, user_id)

            if receipt is None:
                raise ReceiptNotFoundError

            if receipt.status not in {
                ReceiptStatus.FAILED,
                ReceiptStatus.NEED_REVIEW,
                ReceiptStatus.COMPLETED,
            }:
                raise ConflictError("Чек уже ожидает обработки или обрабатывается.")

            if repository.has_items(receipt_id=receipt_id) and not replace_items:
                raise ConflictError(
                    "В чеке уже есть товары. Для их замены передайте replace_items=true."
                )

            repository.prepare_process(receipt=receipt, replace_items=replace_items)

            ticket = ReceiptProcessTicket(
                receipt_id=receipt.receipt_id,
                processing_version=receipt.processing_version,
            )

        return ticket

    def mark_enqueue_unconfirmed(
        self, receipt_id: UUID, processing_version: int
    ) -> None:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return

            if receipt.processing_version != processing_version:
                return

            if receipt.status != ReceiptStatus.UPLOADED:
                return

            if receipt.processing_result_saved_at is not None:
                return

            repository.set_processing_error(
                receipt=receipt,
                status=ReceiptStatus.FAILED,
                error_code="receipt_enqueue_unconfirmed",
                error_message="Не удалось подтвердить постановку чека в очередь обработки.",
            )

    def start_processing(
        self, receipt_id: UUID, processing_version: int = 1
    ) -> ReceiptProcessingInput | None:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return

            if receipt.processing_version != processing_version:
                return

            if receipt.processing_result_saved_at is not None:
                return

            if receipt.status not in {ReceiptStatus.UPLOADED, ReceiptStatus.FAILED}:
                return

            source = ReceiptProcessingInput(
                receipt_id=receipt.receipt_id, image_object_key=receipt.image_object_key
            )

            repository.set_status(
                receipt, ReceiptStatus.PREPROCESSING, clear_error=True
            )

        return source

    def advance_status(
        self,
        receipt_id: UUID,
        expected_status: ReceiptStatus,
        new_status: ReceiptStatus,
        processing_version: int = 1,
    ) -> bool:

        allowed_transitions = {
            (ReceiptStatus.PREPROCESSING, ReceiptStatus.OCR_PROCESSING),
            (ReceiptStatus.OCR_PROCESSING, ReceiptStatus.PARSING),
        }

        if (expected_status, new_status) not in allowed_transitions:
            raise ValueError(
                f"Unsupported processing transition: "
                f"{expected_status.value} -> {new_status.value}"
            )

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False

            if receipt.processing_version != processing_version:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.status != expected_status:
                return False

            repository.set_status(receipt, new_status)

        return True

    def mark_failed(
        self,
        receipt_id: UUID,
        error: Exception | None = None,
        processing_version: int = 1,
    ) -> bool:
        safe_error = get_safe_processing_error(error)

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False

            if receipt.processing_version != processing_version:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.status not in {
                ReceiptStatus.PREPROCESSING,
                ReceiptStatus.OCR_PROCESSING,
                ReceiptStatus.PARSING,
            }:
                return False

            repository.set_processing_error(
                receipt,
                status=ReceiptStatus.FAILED,
                error_code=safe_error.code,
                error_message=safe_error.message,
            )

        return True

    def save_result(
        self,
        receipt_id: UUID,
        result: ReceiptProcessingResult,
        processing_version: int = 1,
    ) -> SaveProcessingOutcome:

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return SaveProcessingOutcome.RECEIPT_DELETED

            if receipt.processing_version != processing_version:
                return SaveProcessingOutcome.STALE_JOB

            if receipt.processing_result_saved_at is not None:
                return SaveProcessingOutcome.ALREADY_SAVED

            if receipt.items_revision != receipt.processing_items_revision:
                raise ReceiptProcessingConflictError()

            if (
                repository.has_items(receipt_id)
                and not receipt.processing_replace_items
            ):
                raise ReceiptProcessingConflictError()

            repository.store_result(
                receipt=receipt,
                items=result.items,
                raw_ocr_text=result.raw_ocr_text,
                saved_at=datetime.now(UTC),
                status=ReceiptStatus.NEED_REVIEW,
            )

        return SaveProcessingOutcome.SAVED

    def mark_interrupted(self, receipt_id: UUID, processing_version: int) -> bool:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False
            if receipt.processing_version != processing_version:
                return False
            if receipt.processing_result_saved_at is not None:
                return False
            if receipt.status not in {
                ReceiptStatus.UPLOADED,
                ReceiptStatus.PREPROCESSING,
                ReceiptStatus.OCR_PROCESSING,
                ReceiptStatus.PARSING,
            }:
                return False

            repository.set_processing_error(
                receipt=receipt,
                status=ReceiptStatus.FAILED,
                error_code="processing_interrupted",
                error_message=(
                    "Обработка чека была прервана. "
                    "Если автоматический повтор недоступен, "
                    "запустите обработку повторно."
                ),
            )

        return True

    def can_retry_processing(self, receipt_id: UUID, processing_version: int) -> bool:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.processing_version != processing_version:
                return False

            return receipt.status in {ReceiptStatus.UPLOADED, ReceiptStatus.FAILED}
