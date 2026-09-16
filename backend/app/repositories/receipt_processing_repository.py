from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Receipt, ReceiptItem
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.request import ReceiptItemCreateRequest


class ReceiptProcessingRepository:
    """Persistence operations; the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_update(self, receipt_id: UUID) -> Receipt | None:
        return self.session.scalar(
            select(Receipt).where(Receipt.receipt_id == receipt_id).with_for_update()
        )

    def has_items(self, receipt_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(ReceiptItem.receipt_item_id)
                .where(ReceiptItem.receipt_id == receipt_id)
                .limit(1)
            )
            is not None
        )

    def set_status(self, receipt: Receipt, status: ReceiptStatus) -> None:
        receipt.status = status
        self.session.flush()

    def store_result(
        self,
        receipt: Receipt,
        items: Sequence[ReceiptItemCreateRequest],
        raw_ocr_text: str | None,
        saved_at: datetime,
        status: ReceiptStatus,
    ) -> None:
        self.session.add_all(
            [
                ReceiptItem(receipt_id=receipt.receipt_id, **item.model_dump())
                for item in items
            ]
        )
        receipt.raw_ocr_text = raw_ocr_text
        receipt.processing_result_saved_at = saved_at
        receipt.status = status
        self.session.flush()
