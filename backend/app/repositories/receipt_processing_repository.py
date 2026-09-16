from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import Receipt, ReceiptItem
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.request import ReceiptItemCreateRequest


class ReceiptProcessingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_update(
        self, receipt_id: UUID, user_id: UUID | None = None
    ) -> Receipt | None:

        query = select(Receipt).where(
            Receipt.receipt_id == receipt_id,
        )

        if user_id is not None:
            query = query.where(
                Receipt.receipt_user_id == user_id,
            )

        return self.session.scalar(query.with_for_update())

    def has_items(self, receipt_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(ReceiptItem.receipt_item_id)
                .where(ReceiptItem.receipt_id == receipt_id)
                .limit(1)
            )
            is not None
        )

    def set_status(
        self, receipt: Receipt, status: ReceiptStatus, clear_error: bool = False
    ) -> None:

        receipt.status = status
        if clear_error:
            receipt.processing_error_code = None
            receipt.processing_error_message = None

        self.session.flush()

    def set_processing_error(
        self,
        receipt: Receipt,
        status: ReceiptStatus,
        error_code: str,
        error_message: str,
    ) -> None:

        receipt.status = status
        receipt.processing_error_code = error_code
        receipt.processing_error_message = error_message

        self.session.flush()

    def prepare_process(self, receipt: Receipt, replace_items: bool) -> None:
        receipt.processing_version += 1
        receipt.processing_items_revision = receipt.items_revision
        receipt.processing_replace_items = replace_items

        receipt.processing_result_saved_at = None
        receipt.processing_error_code = None
        receipt.processing_error_message = None
        receipt.status = ReceiptStatus.UPLOADED

        self.session.flush()

    def store_result(
        self,
        receipt: Receipt,
        items: Sequence[ReceiptItemCreateRequest],
        raw_ocr_text: str | None,
        saved_at: datetime,
        status: ReceiptStatus,
    ) -> None:

        if receipt.processing_replace_items:
            self.session.execute(
                delete(ReceiptItem).where(ReceiptItem.receipt_id == receipt.receipt_id)
            )

        self.session.add_all(
            [
                ReceiptItem(receipt_id=receipt.receipt_id, **item.model_dump())
                for item in items
            ]
        )
        receipt.raw_ocr_text = raw_ocr_text
        receipt.processing_result_saved_at = saved_at
        receipt.status = status

        receipt.processing_error_code = None
        receipt.processing_error_message = None
        receipt.processing_replace_items = False
        receipt.items_revision += 1

        self.session.flush()
