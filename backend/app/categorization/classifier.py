import re

from pydantic import BaseModel, ConfigDict

from backend.app.categorization.catalog import FALLBACK_CATEGORY
from backend.app.categorization.normalization import normalize_category_text
from backend.app.categorization.rules import KEYWORD_RULES, RULE_VERSION


class CategorySuggestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category_name: str
    rule_version: str = RULE_VERSION
    matched_rule: str | None = None
    normalized_text: str


class KeywordCategorizer:
    def suggest(self, name: str) -> CategorySuggestion:
        text = normalize_category_text(name)
        for category, patterns in KEYWORD_RULES:
            for pattern in patterns:
                if re.search(rf"(?<!\w)(?:{pattern})(?!\w)", text):
                    return CategorySuggestion(
                        category_name=category,
                        matched_rule=pattern,
                        normalized_text=text,
                    )
        return CategorySuggestion(category_name=FALLBACK_CATEGORY, normalized_text=text)
