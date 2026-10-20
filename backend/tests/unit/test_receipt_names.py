from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline


@pytest.mark.parametrize(
    ("raw_name", "normalized"),
    [
        ("МОЛОКО 3,2% 900мл", "молоко 3,2% 900мл"),
        (
            "SNICKERS лесной орех 81г(Марс):32/160",
            "snickers лесной орех 81г(марс):32/160",
        ),
        ("4514 ЛУЗИНСКАЯ КРЫНОЧКА 2.5% 900М", "4514 лузинская крыночка 2.5% 900м"),
        ("365 ДНЕЙ 1КГ", "365 дней 1кг"),
        ("7UP 0.5л", "7up 0.5л"),
        ("ПЕЧЕНЬЕ  С  ШОКОЛАДОМ", "печенье с шоколадом"),
        ("RITTER\tSPORT\u00a0ШОКОЛАД", "ritter sport шоколад"),
        ("ЧАИ\u0306 ЗЕЛЕ\u0308НЫИ\u0306", "чай зелёный"),
        ("МОЛОКO", "молокo"),
        ("Сок «ЯБЛОКО» + ВИШНЯ", "сок «яблоко» + вишня"),
    ],
)
def test_parser_preserves_raw_name_and_adds_normalized_name(raw_name, normalized):
    raw = f"{raw_name} 100.00*1шт=100.00\nИТОГ 100.00"
    result = ReceiptParser().parse(raw)
    item = result.items[0]
    assert item.raw_name == raw_name
    assert item.normalized_name == normalized
    assert result.raw_ocr_text == raw
    assert item.quantity == 1
    assert item.unit_price == item.total_price == 100
    assert result.totals_check.status == "matched"


def test_wrapped_name_has_one_line_normalized_form_and_keeps_raw_line_breaks():
    result = ReceiptParser().parse(
        "САЛАТ С ГОВЯЖЬИМ ЯЗЫКОМ\nИ ДОМАШНИМ МАЙОНЕЗОМ\n100.00*1шт=100.00\nИТОГ 100.00"
    )
    item = result.items[0]
    assert item.raw_name == "САЛАТ С ГОВЯЖЬИМ ЯЗЫКОМ\nИ ДОМАШНИМ МАЙОНЕЗОМ"
    assert item.normalized_name == "салат с говяжьим языком и домашним майонезом"


def test_equal_normalized_names_do_not_merge_receipt_lines():
    result = ReceiptParser().parse(
        "МОЛОКО 50.00*1шт=50.00\nМолоко 50.00*1шт=50.00\nИТОГ 100.00"
    )
    assert len(result.items) == 2
    assert [item.raw_name for item in result.items] == ["МОЛОКО", "Молоко"]
    assert [item.normalized_name for item in result.items] == ["молоко", "молоко"]


def test_partial_item_also_keeps_both_names():
    item = ReceiptParser().parse("НЕЯСНЫЙ ТОВАР =90.00\nИТОГ 90.00").items[0]
    assert item.raw_name == "НЕЯСНЫЙ ТОВАР"
    assert item.normalized_name == "неясный товар"
    assert item.quantity is item.unit_price is None


def test_pipeline_carries_both_names_to_persistence_dto():
    result = UnconfiguredReceiptPipeline(Mock(), Mock()).parse(
        "МОЛОКО 100.00*1шт=100.00\nИТОГ 100.00"
    )
    assert result.items[0].raw_name == "МОЛОКО"
    assert result.items[0].normalized_name == "молоко"
    assert result.parsed_receipt.items[0].normalized_name == "молоко"


def test_normalization_is_idempotent_and_handles_blank_input():
    from backend.app.parsing.names import normalize_item_name

    name = normalize_item_name(" \tСОК\n ЯБЛОЧНЫЙ 1Л ")
    assert name == "сок яблочный 1л"
    assert normalize_item_name(name) == name
    assert normalize_item_name(" \t\n") is None


def test_lowercase_expansion_does_not_overflow_database_or_truncate_name():
    raw_name = "İ" * 256
    result = ReceiptParser().parse(f"{raw_name} 100.00*1шт=100.00\nИТОГ 100.00")
    assert result.items[0].raw_name == raw_name
    assert result.items[0].normalized_name is None
    assert any("нормализованное название" in warning for warning in result.warnings)


@pytest.mark.parametrize("number", range(1, 8))
def test_reference_items_all_have_normalized_names(number):
    root = Path(__file__).resolve().parents[1] / "fixtures/ocr/v1/texts"
    raw = (root / f"receipt_{number:03}.txt").read_text(encoding="utf-8-sig")
    result = ReceiptParser().parse(raw)
    assert result.items
    assert all(item.raw_name and item.normalized_name for item in result.items)
    assert all("\n" not in item.normalized_name for item in result.items)
