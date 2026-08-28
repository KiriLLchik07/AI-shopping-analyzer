from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.core.exceptions import ReceiptItemNotFoundError, ReceiptNotFoundError
from backend.app.models.receipt import Receipt, ReceiptItem
from backend.app.repositories.receipt_repository import ReceiptRepository
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
    ReceiptItemUpdateRequest,
    ReceiptListParams,
    ReceiptUpdateRequest,
)


class ReceiptService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.repository = ReceiptRepository(db_session)

    def get_receipts(
        self, user_id: UUID, params: ReceiptListParams
    ) -> tuple[list[Receipt], int]:
        offset = (params.page - 1) * params.page_size

        date_from = (
            datetime.combine(params.date_from, time.min, timezone.utc)
            if params.date_from
            else None
        )

        date_to = (
            datetime.combine(
                params.date_to + timedelta(days=1),
                time.min,
                timezone.utc,
            )
            if params.date_to
            else None
        )

        filters = {
            "date_from": date_from,
            "date_to": date_to,
            "store_name": params.store_name,
            "status": params.status,
        }

        receipts = self.repository.get_receipts(
            user_id=user_id,
            offset=offset,
            limit=params.page_size,
            **filters,
        )
        total = self.repository.count_receipts(user_id, **filters)

        return receipts, total

    def get_receipt_by_id(self, receipt_id: UUID, user_id: UUID) -> Receipt:
        receipt = self.repository.get_receipt_by_id(receipt_id, user_id)
        if receipt is None:
            raise ReceiptNotFoundError

        return receipt

    def update_receipt(
        self, payload: ReceiptUpdateRequest, receipt_id: UUID, user_id: UUID
    ) -> Receipt:
        receipt = self.get_receipt_by_id(receipt_id, user_id)

        update_data = payload.model_dump(exclude_unset=True)

        receipt = self.repository.update_receipt(receipt, update_data)

        self.db_session.commit()
        self.db_session.refresh(receipt)

        return receipt

    def delete_receipt(
        self,
        receipt_id: UUID,
        user_id: UUID,
    ) -> None:

        receipt = self.get_receipt_by_id(
            receipt_id=receipt_id,
            user_id=user_id,
        )

        self.repository.delete_receipt(receipt)
        self.db_session.commit()

    def create_receipt_item(
        self,
        payload: ReceiptItemCreateRequest,
        receipt_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:

        receipt = self.get_receipt_by_id(receipt_id=receipt_id, user_id=user_id)

        item_data = payload.model_dump()

        receipt_item = self.repository.create_receipt_item(
            receipt_id=receipt.receipt_id, item_data=item_data
        )

        self.db_session.commit()
        self.db_session.refresh(receipt_item)

        return receipt_item

    def _get_receipt_item(
        self,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:

        receipt = self.get_receipt_by_id(
            receipt_id=receipt_id,
            user_id=user_id,
        )

        receipt_item = self.repository.get_receipt_item(
            receipt_id=receipt.receipt_id,
            receipt_item_id=receipt_item_id,
        )

        if receipt_item is None:
            raise ReceiptItemNotFoundError

        return receipt_item

    def update_receipt_item(
        self,
        payload: ReceiptItemUpdateRequest,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:
        receipt_item = self._get_receipt_item(
            receipt_id=receipt_id,
            receipt_item_id=receipt_item_id,
            user_id=user_id,
        )

        update_data = payload.model_dump(exclude_unset=True)

        receipt_item = self.repository.update_receipt_item(
            receipt_item=receipt_item,
            update_data=update_data,
        )

        self.db_session.commit()
        self.db_session.refresh(receipt_item)

        return receipt_item

    def delete_receipt_item(
        self,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> None:
        receipt_item = self._get_receipt_item(
            receipt_id=receipt_id,
            receipt_item_id=receipt_item_id,
            user_id=user_id,
        )

        self.repository.delete_receipt_item(receipt_item)
        self.db_session.commit()
