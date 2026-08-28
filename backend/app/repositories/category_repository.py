from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.receipt import Category


class CategoryRepository:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def get_category_by_id(
        self,
        category_id: UUID,
    ) -> Category | None:
        
        return self.db_session.get(Category, category_id)

    def get_categories(self) -> list[Category]:
        
        query = select(Category).order_by(Category.category_name)
        return list(self.db_session.scalars(query).all())
