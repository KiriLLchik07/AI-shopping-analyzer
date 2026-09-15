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

    def get_pending_input(self, receipt_id: UUID) -> ReceiptProcessingInput | None:
        with self.session_factory() as session:
            receipt = session.get(Receipt, receipt_id)

            if receipt is None:
                return

            if receipt.processing_result_saved_at is not None:
                return

            return ReceiptProcessingInput(
                receipt_id=receipt.receipt_id,
                image_object_key=receipt.image_object_key,
            )

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
