from collections.abc import Sequence

from sqlalchemy.orm import Session

from backend.app.categorization.catalog import default_category_id
from backend.app.categorization.classifier import KeywordCategorizer
from backend.app.repositories.category_repository import CategoryRepository
from backend.app.schemas.items import ReceiptItemData


class ReceiptCategorizationService:
    def __init__(self, session: Session) -> None:
        self.repository = CategoryRepository(session)
        self.categorizer = KeywordCategorizer()

    def suggest_items(
        self, items: Sequence[ReceiptItemData]
    ) -> tuple[ReceiptItemData, ...]:
        if not items:
            return ()
        suggestions = [
            self.categorizer.suggest(item.normalized_name or item.raw_name)
            for item in items
        ]
        ids = {
            name: default_category_id(name)
            for name in {s.category_name for s in suggestions}
        }
        if self.repository.get_existing_ids(tuple(ids.values())) != set(ids.values()):
            raise RuntimeError(
                "Default categories are missing; apply database migrations"
            )
        return tuple(
            item.model_copy(
                update={
                    "suggested_category_id": ids[suggestion.category_name],
                    "category_id": item.category_id
                    if item.category_id is not None
                    else ids[suggestion.category_name],
                    "category_rule_version": suggestion.rule_version,
                    "category_source": "automatic",
                    "category_match": suggestion.matched_rule,
                    "category_input": suggestion.normalized_text,
                    "category_confirmed_at": None,
                }
            )
            for item, suggestion in zip(items, suggestions, strict=True)
        )
