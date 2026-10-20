from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import Receipt, ReceiptItem
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.items import ReceiptItemData
from backend.app.schemas.ocr import OcrResult
from backend.app.schemas.orientation import OrientationReport
from backend.app.schemas.parsing import ReceiptParsingResult


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
        self,
        receipt: Receipt,
        status: ReceiptStatus,
        clear_error: bool = False,
        orientation_report: OrientationReport | None = None,
        clear_orientation_report: bool = False,
        clear_ocr_result: bool = False,
    ) -> None:

        receipt.status = status
        if clear_ocr_result:
            receipt.raw_ocr_text = None
            receipt.ocr_confidence = None
            receipt.parsing_report = None
        if clear_orientation_report:
            receipt.orientation_report = None
        elif orientation_report is not None:
            receipt.orientation_report = orientation_report.model_dump(mode="json")
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
        receipt.confirmed_at = None
        receipt.raw_ocr_text = None
        receipt.ocr_confidence = None
        receipt.orientation_report = None
        receipt.parsing_report = None
        receipt.processing_error_code = None
        receipt.processing_error_message = None
        receipt.status = ReceiptStatus.UPLOADED

        self.session.flush()

    def store_ocr_result(self, receipt: Receipt, result: OcrResult) -> None:
        receipt.raw_ocr_text = result.raw_text
        receipt.ocr_confidence = result.confidence
        receipt.status = ReceiptStatus.PARSING
        self.session.flush()

    def store_result(
        self,
        receipt: Receipt,
        items: Sequence[ReceiptItemData],
        raw_ocr_text: str | None,
        saved_at: datetime,
        status: ReceiptStatus,
        parsed_receipt: ReceiptParsingResult | None = None,
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
        if receipt.raw_ocr_text is None:
            receipt.raw_ocr_text = raw_ocr_text
        if parsed_receipt is not None:
            receipt.parsing_report = parsed_receipt.model_dump(
                mode="json", exclude={"raw_ocr_text", "items"}
            )
            manual_fields = set(receipt.manually_updated_fields or ())
            if receipt.store_name is None and "store_name" not in manual_fields:
                receipt.store_name = parsed_receipt.store_name
            if receipt.total_amount is None and "total_amount" not in manual_fields:
                receipt.total_amount = parsed_receipt.total_amount
            purchased_at = parsed_receipt.purchase_datetime
            if (
                receipt.purchase_datetime is None
                and "purchase_datetime" not in manual_fields
                and purchased_at is not None
                and purchased_at.utcoffset() is not None
            ):
                receipt.purchase_datetime = purchased_at
        receipt.processing_result_saved_at = saved_at
        receipt.confirmed_at = None
        receipt.status = status

        receipt.processing_error_code = None
        receipt.processing_error_message = None
        receipt.processing_replace_items = False
        receipt.items_revision += 1

        self.session.flush()
