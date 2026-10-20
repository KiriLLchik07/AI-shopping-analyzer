from decimal import Decimal
from unittest.mock import Mock

import pytest

from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.parsing.units import normalize_unit
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline


@pytest.mark.parametrize(
    ("raw_unit", "unit"),
    [
        ("ШТ.", "шт"),
        ("штук", "шт"),
        ("штука", "шт"),
        ("штуки", "шт"),
        ("КГ", "кг"),
        ("кг.", "кг"),
        ("килограмма", "кг"),
        ("килограммов", "кг"),
        ("гр", "г"),
        ("ГР.", "г"),
        ("грамм", "г"),
        ("граммов", "г"),
        ("Л", "л"),
        ("литра", "л"),
        ("литров", "л"),
        ("МЛ.", "мл"),
        ("миллилитров", "мл"),
        ("уп.", "упак"),
        ("упак.", "упак"),
        ("упаковки", "упак"),
        ("kg", "кг"),
        ("g", "г"),
        ("L", "л"),
        ("ml", "мл"),
        ("pcs", "шт"),
    ],
)
def test_explicit_quantity_units_are_normalized(raw_unit, unit):
    raw = f"Товар 10.00*2{raw_unit}=20.00\nИТОГ 20.00"
    result = ReceiptParser().parse(raw)
    item = result.items[0]
    assert item.raw_name == "Товар"
    assert item.unit == unit
    assert item.quantity == 2
    assert item.unit_price == 10
    assert item.total_price == 20
    assert result.raw_ocr_text == raw
    assert not any("единиц" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "row",
    [
        "Товар 0,432 килограмма ×100,00 ₽=43,20 ₽",
        "Товар\n100,00 руб. 0,432 килограмма 43,20 ₽",
        "Товар\n100,00 руб.\n0,432 килограмма\n43,20 ₽",
    ],
)
def test_full_unit_names_work_in_quantity_first_and_table_formats(row):
    result = ReceiptParser().parse(f"Цена Кол-во ИТОГ\n{row}\nИТОГ 43,20 ₽")
    item = result.items[0]
    assert item.raw_name == "Товар"
    assert item.quantity == Decimal("0.432")
    assert item.unit == "кг"
    assert item.unit_price == 100
    assert item.total_price == Decimal("43.20")


@pytest.mark.parametrize("raw_unit", ["WT", "WT.", "Kr", "WТ", "неизвестно"])
def test_unknown_ocr_units_are_not_guessed(raw_unit):
    result = ReceiptParser().parse(f"Товар 100.00*2{raw_unit}=200.00\nИТОГ 200.00")
    item = result.items[0]
    assert item.unit is None
    assert item.quantity == 2
    assert item.unit_price == 100
    assert item.total_price == 200
    assert any(
        raw_unit in warning and "единиц" in warning for warning in result.warnings
    )
    assert result.totals_check.status == "matched"


@pytest.mark.parametrize("name", ["Молоко 900 мл", "Сахар 1КГ", "Набор 5 шт."])
def test_package_size_in_product_name_does_not_change_purchase_unit(name):
    item = ReceiptParser().parse(f"{name} 100.00*2шт.=200.00\nИТОГ 200.00").items[0]
    assert item.raw_name == name
    assert item.unit == "шт"
    assert item.quantity == 2


def test_missing_purchase_unit_is_not_inferred_from_package_size():
    item = ReceiptParser().parse("Молоко 900 мл 100.00*2=200.00\nИТОГ 200.00").items[0]
    assert item.unit is None
    assert item.quantity == 2


def test_units_are_normalized_without_rescaling_quantity_or_price():
    item = ReceiptParser().parse("Товар 0.10*500ГР.=50.00\nИТОГ 50.00").items[0]
    assert item.unit == "г"
    assert item.quantity == 500
    assert item.unit_price == Decimal("0.10")
    assert item.total_price == 50


def test_pipeline_passes_canonical_unit_to_persistence_dto():
    result = UnconfiguredReceiptPipeline(Mock(), Mock()).parse(
        "Бананы 100.00*0.432КГ=43.20\nИТОГ 43.20"
    )
    assert result.items[0].unit == "кг"
    assert result.parsed_receipt.items[0].unit == "кг"


def test_unit_normalization_handles_outer_whitespace_and_keeps_unknown_values_unknown():
    assert normalize_unit("  КГ.\t") == "кг"
    assert normalize_unit(None) is None
    assert normalize_unit(" ") is None
    assert normalize_unit("К г") is None
    assert normalize_unit("WT") is None
