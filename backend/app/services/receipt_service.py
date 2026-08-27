from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from sqlalchemy.orm import Session

from backend.app.models.receipt import Receipt
from backend.app.repositories.receipt_repository import ReceiptRepository
from backend.app.schemas.request import ReceiptListParams


class ReceiptService:
    def __init__(self, db_session: Session) -> None:
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
