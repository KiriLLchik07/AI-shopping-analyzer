from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.receipt_processing_repository import (
    ReceiptProcessingRepository,
)
from backend.app.schemas.processing import (
    ReceiptProcessingInput,
    ReceiptProcessingResult,
)


class SaveProcessingOutcome(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    RECEIPT_DELETED = "receipt_deleted"


class ReceiptProcessingService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def start_processing(self, receipt_id: UUID) -> ReceiptProcessingInput | None:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return

            if receipt.processing_result_saved_at is not None:
                return

            if receipt.status not in {ReceiptStatus.UPLOADED, ReceiptStatus.FAILED}:
                return

            source = ReceiptProcessingInput(
                receipt_id=receipt.receipt_id, image_object_key=receipt.image_object_key
            )

            repository.set_status(receipt, ReceiptStatus.PREPROCESSING)

        return source

    def advance_status(
        self,
        receipt_id: UUID,
        expected_status: ReceiptStatus,
        new_status: ReceiptStatus,
    ) -> bool:

        allowed_transitions = {
            (ReceiptStatus.PREPROCESSING, ReceiptStatus.OCR_PROCESSING),
            (
                ReceiptStatus.OCR_PROCESSING,
                ReceiptStatus.PARSING,
            ),
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

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.status != expected_status:
                return False

            repository.set_status(receipt, new_status)

        return True

    def mark_failed(
        self,
        receipt_id: UUID,
    ) -> bool:

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.status not in {
                ReceiptStatus.PREPROCESSING,
                ReceiptStatus.OCR_PROCESSING,
                ReceiptStatus.PARSING,
            }:
                return False

            repository.set_status(receipt, ReceiptStatus.FAILED)

        return True

    def save_result(
        self, receipt_id: UUID, result: ReceiptProcessingResult
    ) -> SaveProcessingOutcome:

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return SaveProcessingOutcome.RECEIPT_DELETED

            if receipt.processing_result_saved_at is not None:
                return SaveProcessingOutcome.ALREADY_SAVED

            if repository.has_items(receipt_id):
                raise ReceiptProcessingConflictError()

            repository.store_result(
                receipt=receipt,
                items=result.items,
                raw_ocr_text=result.raw_ocr_text,
                saved_at=datetime.now(UTC),
                status=ReceiptStatus.NEED_REVIEW,
            )

        return SaveProcessingOutcome.SAVED
