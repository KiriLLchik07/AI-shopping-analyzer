from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.models import Receipt, ReceiptItem
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult


class ReceiptProcessingInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    image_object_key: str


class SaveProcessingOutcome(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    RECEIPT_DELETED = "receipt_deleted"


class ReceiptProcessingService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def start_processing(self, receipt_id: UUID) -> ReceiptProcessingInput | None:
        with self.session_factory.begin() as session:
            receipt = session.scalar(
                select(Receipt)
                .where(Receipt.receipt_id == receipt_id)
                .with_for_update()
            )

            if receipt is None:
                return

            if receipt.processing_result_saved_at is not None:
                return

            if receipt.status not in {
                ReceiptStatus.UPLOADED,
                ReceiptStatus.FAILED
            }:
                return

            source = ReceiptProcessingInput(
                receipt_id=receipt.receipt_id,
                image_object_key=receipt.image_object_key
            )

            receipt.status = ReceiptStatus.PREPROCESSING

        return source


    def advance_status(
        self,
        receipt_id: UUID,
        expected_status: ReceiptStatus,
        new_status: ReceiptStatus,
    ) -> bool:

        allowed_transitions = {
            (
                ReceiptStatus.PREPROCESSING,
                ReceiptStatus.OCR_PROCESSING
            ),
            (
                ReceiptStatus.OCR_PROCESSING,
                ReceiptStatus.PARSING,
            )
        }

        if (expected_status, new_status) not in allowed_transitions:
            raise ValueError(
                f"Unsupported processing transition: "
                f"{expected_status.value} -> {new_status.value}"
            )

        with self.session_factory.begin() as session:
            receipt = session.scalar(
                select(Receipt)
                .where(Receipt.receipt_id == receipt_id)
                .with_for_update()
            )

            if receipt is None:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.status != expected_status:
                return False

            receipt.status = new_status

        return True


    def mark_failed(
        self,
        receipt_id: UUID,
    ) -> bool:

        with self.session_factory.begin() as session:
            receipt = session.scalar(
                select(Receipt)
                .where(Receipt.receipt_id == receipt_id)
                .with_for_update()
            )

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

            receipt.status = ReceiptStatus.FAILED

        return True   

    def save_result(
        self, receipt_id: UUID, result: ReceiptProcessingResult
    ) -> SaveProcessingOutcome:

        with self.session_factory.begin() as session:
            receipt = session.scalar(
                select(Receipt)
                .where(Receipt.receipt_id == receipt_id)
                .with_for_update()
            )

            if receipt is None:
                return SaveProcessingOutcome.RECEIPT_DELETED

            if receipt.processing_result_saved_at is not None:
                return SaveProcessingOutcome.ALREADY_SAVED

            existing_item_id = session.scalar(
                select(ReceiptItem.receipt_item_id)
                .where(ReceiptItem.receipt_id == receipt_id)
                .limit(1)
            )

            if existing_item_id:
                raise ReceiptProcessingConflictError()

            session.add_all(
                [
                    ReceiptItem(receipt_id=receipt_id, **item.model_dump())
                    for item in result.items
                ]
            )

            receipt.raw_ocr_text = result.raw_ocr_text
            receipt.status = ReceiptStatus.NEED_REVIEW
            receipt.processing_result_saved_at = datetime.now(timezone.utc)

            session.flush()

        return SaveProcessingOutcome.SAVED
