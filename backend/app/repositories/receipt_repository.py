from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.enums import ReceiptStatus
from backend.app.models.receipt import Receipt, ReceiptItem


class ReceiptRepository:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def _build_filters(
        self,
        user_id: UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        store_name: str | None,
        status: ReceiptStatus | None,
    ):
        filters = [Receipt.receipt_user_id == user_id]

        if date_from is not None:
            filters.append(Receipt.purchase_datetime >= date_from)
        if date_to is not None:
            filters.append(Receipt.purchase_datetime < date_to)
        if store_name is not None:
            filters.append(Receipt.store_name.icontains(store_name, autoescape=True))
        if status is not None:
            filters.append(Receipt.status == status)
        return filters

    def get_receipts(
        self,
        user_id: UUID,
        offset: int,
        limit: int,
        date_from: datetime | None,
        date_to: datetime | None,
        store_name: str | None,
        status: ReceiptStatus | None,
    ) -> list[Receipt]:
        filters = self._build_filters(user_id, date_from, date_to, store_name, status)
        query = (
            select(Receipt)
            .where(*filters)
            .order_by(Receipt.created_at.desc(), Receipt.receipt_id.desc())
            .offset(offset)
            .limit(limit)
        )

        receipts = list(self.db_session.scalars(query).all())
        return receipts

    def count_receipts(
        self,
        user_id: UUID,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        store_name: str | None,
        status: ReceiptStatus | None,
    ) -> int:
        filters = self._build_filters(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            store_name=store_name,
            status=status,
        )

        query = select(func.count()).select_from(Receipt).where(*filters)

        return self.db_session.scalar(query) or 0

    def get_receipt_by_id(self, receipt_id: UUID, user_id: UUID) -> Receipt | None:
        query = select(Receipt).where(
            Receipt.receipt_id == receipt_id, Receipt.receipt_user_id == user_id
        )

        return self.db_session.scalars(query).one_or_none()

    def update_receipt(
        self, receipt: Receipt, update_data: dict[str, object]
    ) -> Receipt:

        for field, value in update_data.items():
            setattr(receipt, field, value)

        self.db_session.flush()
        return receipt

    def delete_receipt(self, receipt: Receipt) -> None:
        self.db_session.delete(receipt)
        self.db_session.flush()

    def create_receipt_item(
        self, receipt_id: UUID, item_data: dict[str, object]
    ) -> ReceiptItem:

        receipt_item = ReceiptItem(receipt_id=receipt_id, **item_data)

        self.db_session.add(receipt_item)
        self.db_session.flush()

        return receipt_item

    def get_receipt_item(
        self,
        receipt_id: UUID,
        receipt_item_id: UUID,
    ) -> ReceiptItem | None:

        query = select(ReceiptItem).where(
            ReceiptItem.receipt_id == receipt_id,
            ReceiptItem.receipt_item_id == receipt_item_id,
        )

        return self.db_session.scalars(query).one_or_none()

    def update_receipt_item(
        self,
        receipt_item: ReceiptItem,
        update_data: dict[str, object],
    ) -> ReceiptItem:

        for field, value in update_data.items():
            setattr(receipt_item, field, value)

        self.db_session.flush()
        return receipt_item

    def delete_receipt_item(
        self,
        receipt_item: ReceiptItem,
    ) -> None:

        self.db_session.delete(receipt_item)
        self.db_session.flush()
