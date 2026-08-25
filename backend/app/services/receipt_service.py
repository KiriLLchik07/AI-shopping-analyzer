from uuid import UUID
from sqlalchemy.orm import Session

from backend.app.models.receipt import Receipt
from backend.app.repositories.receipt_repository import ReceiptRepository

class ReceiptService:
    def __init__(self, db_session: Session) -> None:
        self.repository = ReceiptRepository(db_session)

    def get_receipts(
        self,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Receipt], int]:
        offset = (page - 1) * page_size
        receipts = self.repository.get_receipts(
            user_id=user_id,
            offset=offset,
            limit=page_size,
        )
        total = self.repository.count_receipts(user_id)

        return receipts, total
