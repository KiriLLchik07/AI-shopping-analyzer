from sqlalchemy.orm import Session

from backend.app.models.receipt import Category
from backend.app.repositories.category_repository import CategoryRepository


class CategoryService:
    def __init__(self, db_session: Session) -> None:
        self.repository = CategoryRepository(db_session)

    def get_categories(self) -> list[Category]:
        return self.repository.get_categories()
