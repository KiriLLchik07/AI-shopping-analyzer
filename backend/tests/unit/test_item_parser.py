import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline


@pytest.mark.parametrize(
    ("row", "quantity", "price", "total", "unit"),
    [
        ("Молоко 100.00*2шт. =200.00", "2", "100.00", "200.00", "шт"),
        ("Молоко 100,00 × 2 = 200,00", "2", "100.00", "200.00", None),
        ("Молоко 2 шт x 100.00 =200.00", "2", "100.00", "200.00", "шт"),
        ("Молоко\n100.00 *2 =200.00", "2", "100.00", "200.00", None),
        ("Бананы\n169.99*0.432КГ =73.44", "0.432", "169.99", "73.44", "кг"),
    ],
)
def test_explicit_item_calculation(row, quantity, price, total, unit):
    result = ReceiptParser().parse(f"{row}\nИТОГ {total}")
    assert len(result.items) == 1
    item = result.items[0]
    assert item.raw_name in {"Молоко", "Бананы"}
    assert item.quantity == Decimal(quantity)
    assert item.unit_price == Decimal(price)
    assert item.total_price == Decimal(total)
    assert item.unit == unit
    assert item.confidence is item.normalized_name is None


@pytest.mark.parametrize(
    "row",
    [
        "Бананы 1КГ\n169.99 169.99 0.432КГ 73.44",
        "Бананы 1КГ 169.99 169.99 0.432КГ 73.44",
        "Бананы 1КГ\nНДС 22% 169.99 169.99 0.432КГ 73.44",
        "Бананы 1КГ\n169.99\n169.99\n0.432КГ\n73.44",
        "Бананы 1КГ\n169.99 169.99\n0.432КГ\n73.44",
    ],
)
def test_table_and_separate_ocr_fragments(row):
    result = ReceiptParser().parse(
        f"Цена до скидки Цена Кол-во ИТОГО\n{row}\nИТОГ 73.44"
    )
    assert len(result.items) == 1
    item = result.items[0]
    assert item.raw_name == "Бананы 1КГ"
    assert item.quantity == Decimal("0.432")
    assert item.unit_price == Decimal("169.99")
    assert item.total_price == Decimal("73.44")


def test_current_price_is_taken_from_column_before_quantity():
    result = ReceiptParser().parse(
        "ЦЕНА ЦЕНА СО СКИДКОЙ КОЛ-ВО ИТОГ\n"
        "Печенье 232г\n159.99 96.99 1шт. 96.99\nИТОГ 96.99"
    )
    assert result.items[0].raw_name == "Печенье 232г"
    assert result.items[0].unit_price == Decimal("96.99")


def test_wrapped_names_and_repeated_items_keep_order_and_raw_spelling():
    result = ReceiptParser().parse(
        "Салат с говяжьим языком\nи домашним майонезом\n590.00*1шт. =590.00\n"
        "НДС не облагается\nБешпармак 780.00*1шт =780.00\n"
        "Бешпармак 780.00*1шт =780.00\nИТОГ 2150.00"
    )
    assert [item.raw_name for item in result.items] == [
        "Салат с говяжьим языком\nи домашним майонезом",
        "Бешпармак",
        "Бешпармак",
    ]


def test_service_and_promotion_lines_are_not_products():
    result = ReceiptParser().parse(
        "МАГНИТ\nВАШ КУПОН НА СКИДКУ\nПокупка от 700 руб\n1 купон на 1 чек\n"
        "ЦЕНА ЦЕНА СО СКИДКОЙ КОЛ-ВО ИТОГ\nМолоко\n99.99 89.99 1шт 89.99\n"
        "ИТОГ БЕЗ СКИДОК 99.99\nСКИДКА 10.00\nИТОГ 89.99\n"
        "БЕЗНАЛИЧНЫМИ 89.99\nРеклама 10.00*1шт =10.00"
    )
    assert [item.raw_name for item in result.items] == ["Молоко"]


def test_partial_item_keeps_total_without_inventing_quantity_or_price():
    result = ReceiptParser().parse("Неясный товар =90.00\nИТОГ 90.00")
    assert len(result.items) == 1
    item = result.items[0]
    assert item.quantity is item.unit_price is None
    assert item.total_price == Decimal("90.00")
    assert any("количество" in warning for warning in result.warnings)


def test_table_with_missing_price_keeps_quantity_and_total():
    result = ReceiptParser().parse("ЦЕНА КОЛ-ВО ИТОГ\nТовар\n2шт 90.00\nИТОГ 90.00")
    assert result.items[0].quantity == 2
    assert result.items[0].unit_price is None
    assert result.items[0].total_price == 90


@pytest.mark.parametrize("value", ["0", "-1", "0.0001", "1000000000000"])
def test_invalid_or_unrepresentable_quantity_becomes_unknown(value):
    result = ReceiptParser().parse(f"Товар 10.00*{value}шт =10.00\nИТОГ 10.00")
    assert len(result.items) == 1
    assert result.items[0].quantity is None
    assert result.items[0].total_price == 10
    assert result.warnings


def test_free_item_keeps_zero_prices():
    item = ReceiptParser().parse("Подарок 0.00*1шт =0.00\nИТОГ 100.00").items[0]
    assert item.unit_price == item.total_price == 0


def test_grouped_prices_are_not_mistaken_for_part_of_the_name():
    item = ReceiptParser().parse("Чайник 1 200,00*2шт =2 400,00\nИТОГ 2400.00").items[0]
    assert item.raw_name == "Чайник"
    assert item.unit_price == 1200
    assert item.total_price == 2400


def test_promotion_word_inside_product_name_is_preserved():
    item = (
        ReceiptParser().parse("Шоколад Акция 100.00*1шт =100.00\nИТОГ 100.00").items[0]
    )
    assert item.raw_name == "Шоколад Акция"


def test_orphan_numeric_row_does_not_create_fake_name():
    result = ReceiptParser().parse("ОНЛАЙН-КАССА\nАТОЛ\n100.00*1шт=100.00\nИТОГ 100.00")
    assert result.items == ()
    assert any("название" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("number", "totals", "quantities"),
    [
        (1, ["280", "280", "780", "780", "590", "130", "190", "210"], ["1"] * 8),
        (2, ["57.99", "57.99", "83.99", "89.99", "79.99", "96.99"], ["1"] * 6),
        (3, ["79.99"], ["1"]),
        (4, ["69.00"], ["1"]),
        (5, ["79.99", "139.99", "74.99"], ["1"] * 3),
        (6, ["294.00"], ["1"]),
        (7, ["99.99", "56.99", "73.44"], ["1", "1", "0.432"]),
    ],
)
def test_reference_receipts_items(number, totals, quantities):
    root = Path(__file__).resolve().parents[1] / "fixtures/ocr/v1/texts"
    raw = (root / f"receipt_{number:03}.txt").read_text(encoding="utf-8-sig")
    result = ReceiptParser().parse(raw)
    assert [item.total_price for item in result.items] == list(map(Decimal, totals))
    assert [item.quantity for item in result.items] == list(map(Decimal, quantities))
    assert all(item.unit_price is not None for item in result.items)
    assert not any(
        "Товар" in warning or "Строка" in warning for warning in result.warnings
    )


def test_pipeline_maps_parsed_items_to_processing_data():
    result = UnconfiguredReceiptPipeline(Mock(), Mock()).parse(
        "Бананы 169.99*0.432кг =73.44\nИТОГ 73.44"
    )
    assert result.items[0].quantity == Decimal("0.432")
    assert result.items[0].raw_name == result.parsed_receipt.items[0].raw_name


def test_split_calculation_keeps_name_across_tax_line_and_flags_unknown_unit():
    result = ReceiptParser().parse(
        "Молоко\n100.00*2WT.\nНДС не облагается\n=200.00\nИТОГ 200.00"
    )
    item = result.items[0]
    assert item.raw_name == "Молоко"
    assert item.quantity == 2
    assert item.unit_price == 100
    assert item.unit is None
    assert "WT." in result.raw_ocr_text
    assert any("WT." in warning for warning in result.warnings)


def test_split_header_is_not_mistaken_for_receipt_footer():
    result = ReceiptParser().parse(
        "ЦEHA\nЦЕНА СО СКИДКОЙ\nКОЛ-BО\nИTOГ\nМолоко\n100.00\n90.00\n1WT\n90.00\nИТОГ 90.00"
    )
    assert result.items[0].raw_name == "Молоко"
    assert result.items[0].unit_price == 90
    assert result.items[0].quantity == 1


def test_corrupt_numeric_fragment_does_not_become_part_of_product_name():
    item = ReceiptParser().parse("Комбо\nM294.00*1WT.\n=294.00\nИТОГ 294.00").items[0]
    assert item.raw_name == "Комбо"
    assert item.quantity is item.unit_price is None
    assert item.total_price == 294


def test_extra_table_number_is_not_used_to_guess_column_positions():
    result = ReceiptParser().parse(
        "Цена Кол-во ИТОГ\nБананы\n169.99\n169.99\n3 0.432Kr\n73.44\nИТОГ 73.44"
    )
    item = result.items[0]
    assert item.raw_name == "Бананы"
    assert item.quantity is item.unit_price is None
    assert item.total_price == Decimal("73.44")
    assert any("требуют проверки" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("number", "count", "partial"),
    [(1, 8, 0), (2, 6, 0), (3, 0, 0), (4, 1, 0), (5, 0, 0), (6, 1, 1), (7, 3, 1)],
)
def test_captured_real_ocr_fragments(number, count, partial):
    root = Path(__file__).resolve().parents[1] / "fixtures/parsing/v1"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sample = manifest["samples"][number - 1]
    assert sample["id"] == f"receipt_{number:03}"
    source_root = root.parents[1] / "ocr/v1"
    source_manifest = json.loads(
        (source_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["runtime"] == source_manifest["runtime"]
    assert (
        hashlib.sha256(
            (source_root / "images" / f"receipt_{number:03}.jpg").read_bytes()
        ).hexdigest()
        == sample["source_image_sha256"]
    )
    text = (root / "ocr" / f"receipt_{number:03}.txt").read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == sample["sha256"]
    result = ReceiptParser().parse(text)
    assert len(result.items) == count
    assert (
        sum(item.quantity is None or item.unit_price is None for item in result.items)
        == partial
    )
    assert all(
        "*" not in item.raw_name and "=" not in item.raw_name for item in result.items
    )
    if count == 0 or partial:
        assert any(
            "Строка" in warning or "Товарные" in warning for warning in result.warnings
        )
