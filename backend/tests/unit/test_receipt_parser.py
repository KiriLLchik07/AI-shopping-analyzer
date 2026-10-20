from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from backend.app.core.config import ParsingSettings
from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline
from pydantic import ValidationError


@pytest.mark.parametrize(
    "date_text",
    ["20.10.2026", "20/10/2026", "20-10-2026", "20.10.26", "2026-10-20"],
)
@pytest.mark.parametrize("time_text", ["17:46", "17:46:03"])
def test_extracts_metadata_with_configured_timezone(date_text, time_text):
    raw = f'ООО "Тестовый магазин"\nДата: {date_text} {time_text}\nИТОГ 3 240,00 ₽\n'
    result = ReceiptParser("Asia/Omsk").parse(raw)
    assert result.store_name == 'ООО "Тестовый магазин"'
    assert (
        result.purchase_datetime.isoformat()
        == f"2026-10-20T{time_text if len(time_text) == 8 else time_text + ':00'}+06:00"
    )
    assert result.total_amount == Decimal("3240.00")
    assert result.raw_ocr_text == raw
    assert result.items == ()
    assert result.warnings == ()


@pytest.mark.parametrize(
    "text",
    [
        "ИТОГ =1234.56",
        "ИТОГО: 1 234,56 руб.",
        "ИТОГО К ОПЛАТЕ 1234,56 ₽",
        "СУММА К ОПЛАТЕ: 1234.56",
        "К ОПЛАТЕ\n1234,56",
        "ИТОГ 1\u00a0234,56",
        "ИТОГ 1\u202f234.56 р.",
    ],
)
def test_total_labels_currency_and_grouping(text):
    assert ReceiptParser().parse(text).total_amount == Decimal("1234.56")


def test_ignores_subtotals_payment_tax_and_item_table():
    result = ReceiptParser().parse(
        "ЦЕНА КОЛ-ВО ИТОГ\nИТОГ БЕЗ СКИДОК 529.94\nСКИДКА 63.00\n"
        "ИТОГ 466.94\nПОДЫТОГ 500.00\nНАЛИЧНЫМИ 1000.00\n"
        "СДАЧА 533.06\nСУММА НДС 22% = 84.20\n"
    )
    assert result.total_amount == Decimal("466.94")


@pytest.mark.parametrize(
    "text",
    [
        "ИТОГ -10.00",
        "ИТОГ 0.00",
        "ИТОГ 10000000000.00",
        "ИТОГ 1.234.56",
        "ИТОГ 12,345",
        "ИТОГ БЕЗ СКИДОК 100.00",
        "МОЛОКО 100.00\nБЕЗНАЛИЧНЫМИ 100.00",
        "ИТОГ\nКОЛ-ВО 1 СУММА 100.00",
    ],
)
def test_invalid_or_unlabelled_totals_are_not_guessed(text):
    result = ReceiptParser().parse(text)
    assert result.total_amount is None
    assert any("сумма" in warning for warning in result.warnings)


def test_equal_repeated_totals_are_allowed_but_conflicts_require_review():
    assert ReceiptParser().parse("ИТОГ 69.00\nИТОГО К ОПЛАТЕ 69,00").total_amount == 69
    result = ReceiptParser().parse("ИТОГ 69.00\nК ОПЛАТЕ 79.00")
    assert result.total_amount is None
    assert any("неоднозначно" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "text",
    [
        "Дата: 20.10.2026\nВремя: 17:46",
        "20.10.2026\n17:46",
        "2026-10-20T17:46:00",
    ],
)
def test_unknown_timezone_keeps_local_time_in_result_with_warning(text):
    result = ReceiptParser().parse(text)
    assert result.purchase_datetime.isoformat() == "2026-10-20T17:46:00"
    assert result.purchase_datetime.tzinfo is None
    assert any("PARSING_TIMEZONE" in warning for warning in result.warnings)


def test_explicit_offset_is_preserved_instead_of_configured_timezone():
    result = ReceiptParser("Asia/Omsk").parse("2026-10-20T17:46:00+03:00")
    assert result.purchase_datetime.isoformat() == "2026-10-20T17:46:00+03:00"
    assert ReceiptParser().parse("2026-10-20T17:46:00Z").purchase_datetime == datetime(
        2026, 10, 20, 17, 46, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "text",
    [
        "31.02.2026 17:46",
        "20.10.2026 25:10",
        "20.10.2026 17:46:99",
        "20.10.2026",
        "Годен до 20.10.2026 17:46",
        "Акция с 20.10.2026 17:46",
        "С 20.10.2026 по 21.10.2026 17:46",
        "20.10.2026\nИТОГ 1746.00",
        "20.10.2026 17:46\n21.10.2026 17:46",
    ],
)
def test_invalid_promotion_and_ambiguous_dates_require_review(text):
    result = ReceiptParser("Asia/Omsk").parse(text)
    assert result.purchase_datetime is None
    assert any("Дата" in warning for warning in result.warnings)


@pytest.mark.parametrize("text", ["29.03.2026 02:30", "25.10.2026 02:30"])
def test_dst_nonexistent_and_ambiguous_time_is_not_assigned_a_guessed_offset(text):
    result = ReceiptParser("Europe/Berlin").parse(text)
    assert result.purchase_datetime is not None
    assert result.purchase_datetime.tzinfo is None
    assert any("перевода часов" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "name", ["МАГНИТ", "Пятёрочка", 'ООО "Каштан"', "Магазин Ромашка"]
)
def test_explicit_merchant_names(name):
    assert ReceiptParser().parse(name).store_name == name


def test_repeated_brand_is_not_confused_with_promotion_text_or_register_vendor():
    result = ReceiptParser().parse(
        'ОНЛАЙН-КАССА\nАТОЛ\nМАГНИТ\nМагнит\nМагазин Магнит АСИК\nООО "Тандер"'
    )
    assert result.store_name == "МАГНИТ"


@pytest.mark.parametrize(
    "text",
    ["АТОЛ\nКассовый чек", "Молоко\nИТОГ 100.00", "МАГНИТ\nЛЕНТА", "ООО " + "x" * 101],
)
def test_unknown_ambiguous_or_too_long_merchant_is_not_guessed(text):
    assert ReceiptParser().parse(text).store_name is None


@pytest.mark.parametrize(
    ("number", "total", "store"),
    [
        (1, "3240.00", None),
        (2, "466.94", "МАГНИТ"),
        (3, "79.99", "МАГНИТ"),
        (4, "69.00", None),
        (5, "294.97", "МАГНИТ"),
        (6, "294.00", None),
        (7, "230.42", "Пятёрочка"),
    ],
)
def test_redacted_receipt_references(number, total, store):
    path = Path(__file__).resolve().parents[1] / "fixtures" / "ocr" / "v1" / "texts"
    text = (path / f"receipt_{number:03}.txt").read_text(encoding="utf-8-sig")
    result = ReceiptParser().parse(text)
    assert result.raw_ocr_text == text
    assert result.total_amount == Decimal(total)
    assert result.store_name == store
    assert result.purchase_datetime is None


def test_pipeline_runs_real_parser_and_does_not_fabricate_items():
    pipeline = UnconfiguredReceiptPipeline(
        Mock(), Mock(), parser=ReceiptParser("Asia/Omsk")
    )
    result = pipeline.parse("МАГНИТ\n20.10.2026 17:46\nИТОГ 100.00")
    assert result.parsed_receipt.store_name == "МАГНИТ"
    assert result.parsed_receipt.total_amount == Decimal("100.00")
    assert result.items == ()


def test_empty_text_is_partial_result_not_technical_failure():
    result = ReceiptParser().parse("")
    assert result.store_name is result.purchase_datetime is result.total_amount is None
    assert len(result.warnings) == 3


def test_parsing_timezone_settings_are_optional_and_validated():
    assert ParsingSettings(_env_file=None, timezone=None).timezone is None
    assert ParsingSettings(_env_file=None, timezone="Asia/Omsk").timezone == "Asia/Omsk"
    with pytest.raises(ValidationError):
        ParsingSettings(_env_file=None, timezone="Invalid/Timezone")
