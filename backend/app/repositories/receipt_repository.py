from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.receipt import Receipt

class ReceiptRepository:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def get_receipts(
        self,
        user_id: UUID,
        offset: int,
        limit: int,
    ) -> list[Receipt]:
        query = (
            select(Receipt)
            .where(Receipt.receipt_user_id == user_id)
            .order_by(Receipt.created_at.desc(), Receipt.receipt_id.desc())
            .offset(offset)
            .limit(limit)
        )

        receipts = list(self.db_session.scalars(query).all())
        return receipts

    def count_receipts(self, user_id: UUID) -> int:
        query = (
            select(func.count())
            .select_from(Receipt)
            .where(Receipt.receipt_user_id == user_id)
        )

        return self.db_session.scalar(query) or 0
