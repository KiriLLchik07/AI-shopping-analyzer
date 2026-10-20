import importlib.util
import json
from pathlib import Path

import pytest

from backend.app.categorization.catalog import (
    DEFAULT_CATEGORIES,
    FALLBACK_CATEGORY,
    default_category_id,
)
from backend.app.categorization.classifier import KeywordCategorizer
from backend.app.categorization.normalization import normalize_category_text
from backend.app.categorization.rules import KEYWORD_RULES, RULE_VERSION

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/categorization/v1/cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_categorization_regression(case):
    result = KeywordCategorizer().suggest(case["name"])
    assert result.category_name == case["category"]
    assert result.rule_version == RULE_VERSION
    assert (result.matched_rule is None) == (case["category"] == FALLBACK_CATEGORY)


@pytest.mark.parametrize("name", ["", " \n\t ", "12345", "UNKNOWN ITEM"])
def test_unknown_text_falls_back_without_guessed_score(name):
    result = KeywordCategorizer().suggest(name)
    assert result.category_name == FALLBACK_CATEGORY
    assert result.matched_rule is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("  МОЛОКО\t3.2%\u00a0900МЛ  ", "молоко 3 2 900мл"),
        ("ЛАП. Б/П ГОВ.", "лапша быстрого приготовления говядина"),
        ("ЗУБ. ПАСТА", "зубная паста"),
        ("ЧАИ\u0306 ЗЕЛЕ\u0308НЫИ\u0306", "чай зеленый"),
        ("ＳＰＯＴＩＦＹ", "spotify"),
    ],
)
def test_normalization_is_idempotent(name, expected):
    assert normalize_category_text(name) == expected
    assert normalize_category_text(expected) == expected


def test_catalog_matches_existing_seed_ids_and_all_categories_are_covered():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/1c8f59ea29ac_seed_default_categories.py"
    )
    spec = importlib.util.spec_from_file_location("category_seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert tuple(module.CATEGORY_NAMES) == DEFAULT_CATEGORIES
    assert all(
        default_category_id(name) == module.get_category_id(name)
        for name in DEFAULT_CATEGORIES
    )
    assert {case["category"] for case in CASES} == set(DEFAULT_CATEGORIES)
    assert {category for category, _ in KEYWORD_RULES} == set(DEFAULT_CATEGORIES) - {
        FALLBACK_CATEGORY
    }


def test_baseline_accuracy_and_fallback_rate():
    predicted = [
        KeywordCategorizer().suggest(case["name"]).category_name for case in CASES
    ]
    correct = sum(
        label == case["category"] for label, case in zip(predicted, CASES, strict=True)
    )
    accuracy = correct / len(CASES)
    fallback_rate = predicted.count(FALLBACK_CATEGORY) / len(CASES)
    assert accuracy >= 0.90, f"accuracy={accuracy:.2%}, fallback={fallback_rate:.2%}"
    assert fallback_rate < 0.20
