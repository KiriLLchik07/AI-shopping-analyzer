from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("1 234,50 ₽", "1234.50"),
        ("1\u00a0234,50 руб.", "1234.50"),
        ("1\u202f234.50 р.", "1234.50"),
        ("1234,5 рублей", "1234.5"),
        ("1234.50 RUB", "1234.50"),
        ("1234₽", "1234"),
        ("1234 руб", "1234"),
    ],
)
def test_money_formats_work_for_total_and_item(amount, expected):
    raw = f"Товар {amount} *1шт ={amount}\nИТОГ {amount}"
    result = ReceiptParser().parse(raw)
    assert result.total_amount == Decimal(expected)
    assert len(result.items) == 1
    assert result.items[0].raw_name == "Товар"
    assert result.items[0].unit_price == Decimal(expected)
    assert result.items[0].total_price == Decimal(expected)
    assert result.raw_ocr_text == raw


@pytest.mark.parametrize(
    "row",
    [
        "Товар 100,00 ₽ * 2шт = 200,00 руб.",
        "Товар 2шт ×100.00 руб. =200,00 ₽",
        "Товар\n100,00 ₽*2шт\n=200,00 ₽",
        "Товар\n100,00\nруб.\n*2шт\n=200,00\n₽",
    ],
)
def test_currency_in_explicit_calculations_and_ocr_fragments(row):
    item = ReceiptParser().parse(f"{row}\nИТОГ 200,00 ₽").items[0]
    assert item.raw_name == "Товар"
    assert item.unit_price == 100
    assert item.quantity == 2
    assert item.total_price == 200


@pytest.mark.parametrize(
    "row",
    [
        "Товар\n120,00 ₽ 100,00 руб. 2шт 200,00 ₽",
        "Товар\n120,00 ₽\n100,00 руб.\n2шт\n200,00 ₽",
        "Товар\n2шт 200,00 ₽",
    ],
)
def test_table_currency(row):
    item = (
        ReceiptParser()
        .parse(f"Цена Цена со скидкой Кол-во ИТОГ\n{row}\nИТОГ 200,00 ₽")
        .items[0]
    )
    assert item.raw_name == "Товар"
    assert item.quantity == 2
    assert item.total_price == 200
    assert item.unit_price == (None if "120" not in row else Decimal("100.00"))


def test_currency_words_in_name_are_not_removed():
    item = (
        ReceiptParser()
        .parse("Руб. Рубиновый сувенир 100,00₽*1шт=100,00₽\nИТОГ 100,00₽")
        .items[0]
    )
    assert item.raw_name == "Руб. Рубиновый сувенир"


def test_fractional_quantity_uses_decimal_comma_independently_of_money():
    item = (
        ReceiptParser().parse("Бананы 169,99 руб.*0,432кг=73,44₽\nИТОГ 73,44₽").items[0]
    )
    assert item.quantity == Decimal("0.432")
    assert item.unit_price == Decimal("169.99")
    assert item.total_price == Decimal("73.44")


@pytest.mark.parametrize(
    "amount",
    ["1,234.50 ₽", "1.234,50 ₽", "12 34,50 ₽", "100,001 ₽", "100 USD", "100 €"],
)
def test_malformed_or_foreign_amount_is_not_accepted_as_rubles(amount):
    assert ReceiptParser().parse(f"ИТОГ {amount}").total_amount is None


@pytest.mark.parametrize(
    "date_text",
    ["1.2.2026", "01/02/26", "1-2-26", "2026/02/01", "2026.2.1", "2026-02-01"],
)
def test_date_formats_use_day_month_order_and_explicit_year(date_text):
    result = ReceiptParser("Asia/Omsk").parse(f"Дата: {date_text} 09:05:03")
    assert result.purchase_datetime.isoformat() == "2026-02-01T09:05:03+06:00"


def test_date_time_on_separate_lines_and_spaced_utc_offset():
    result = ReceiptParser("Asia/Omsk").parse("Дата: 1/2/2026\nВремя: 09:05 +03:00")
    assert result.purchase_datetime.isoformat() == "2026-02-01T09:05:00+03:00"
    assert ReceiptParser().parse("2026/02/01 09:05 Z").purchase_datetime == datetime(
        2026, 2, 1, 9, 5, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "value", ["31/02/2026 09:05", "1.2/2026 09:05", "02/01/26", "1.2.2026 24:01"]
)
def test_invalid_or_incomplete_dates_are_not_guessed(value):
    assert ReceiptParser().parse(value).purchase_datetime is None


def test_pipeline_passes_normalized_values_to_storage_dto():
    pipeline = UnconfiguredReceiptPipeline(
        Mock(), Mock(), parser=ReceiptParser("Asia/Omsk")
    )
    result = pipeline.parse(
        "МАГНИТ\nДата: 1.2.2026 09:05\nТовар 100,5₽*2шт=201,00 ₽\nИТОГ 201,00 ₽"
    )
    assert result.items[0].unit_price == Decimal("100.5")
    assert result.items[0].raw_name == "Товар"
    assert result.items[0].total_price == Decimal("201.00")
    assert (
        result.parsed_receipt.purchase_datetime.isoformat()
        == "2026-02-01T09:05:00+06:00"
    )
