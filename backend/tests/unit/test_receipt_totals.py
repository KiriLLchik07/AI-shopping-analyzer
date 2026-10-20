from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import ParsingSettings
from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.schemas.parsing import ParsedReceiptItem, ReceiptParsingReport


@pytest.mark.parametrize(
    ("total", "status", "difference"),
    [
        ("100.00", "matched", "0.00"),
        ("100.01", "within_tolerance", "-0.01"),
        ("100.05", "within_tolerance", "-0.05"),
        ("99.95", "within_tolerance", "0.05"),
        ("100.06", "mismatch", "-0.06"),
        ("99.94", "mismatch", "0.06"),
    ],
)
def test_sum_comparison_is_exact_and_tolerance_boundary_is_inclusive(
    total, status, difference
):
    result = ReceiptParser().parse(f"Товар 50.00*2шт=100.00\nИТОГ {total}")
    check = result.totals_check
    assert check.status == status
    assert check.items_sum == Decimal("100.00")
    assert check.difference == Decimal(difference)
    assert check.tolerance == Decimal("0.05")
    assert check.item_count == 1
    assert check.missing_amount_count == 0
    assert any("Сумма позиций" in warning for warning in result.warnings) == (
        status == "mismatch"
    )
    assert result.total_amount == Decimal(total)
    assert result.items[0].total_price == Decimal("100.00")


def test_duplicate_rows_are_summed_individually_using_line_totals():
    result = ReceiptParser().parse(
        "Молоко 50.00*2шт=100.00\nМолоко 50.00*2шт=100.00\nИТОГ 200.00"
    )
    assert len(result.items) == 2
    assert result.totals_check.items_sum == Decimal("200.00")
    assert result.totals_check.status == "matched"


def test_decimal_arithmetic_does_not_introduce_float_error():
    result = ReceiptParser().parse(
        "Первый 0.10*1шт=0.10\nВторой 0.20*1шт=0.20\nИТОГ 0.30"
    )
    assert result.totals_check.items_sum == Decimal("0.30")
    assert result.totals_check.difference == 0
    assert result.totals_check.status == "matched"


def test_large_receipt_does_not_hide_a_ruble_difference_behind_percentage_tolerance():
    result = ReceiptParser().parse("Товар 100000.00*1шт=100000.00\nИТОГ 99999.00")
    assert result.totals_check.status == "mismatch"
    assert result.totals_check.difference == 1


def test_unknown_quantity_does_not_prevent_comparing_known_line_total():
    result = ReceiptParser().parse("Товар =90.00\nИТОГ 90.00")
    assert result.items[0].quantity is None
    assert result.totals_check.status == "matched"


def test_missing_receipt_total_is_not_invented_from_items():
    result = ReceiptParser().parse("Товар 50.00*2шт=100.00")
    assert result.total_amount is None
    assert result.totals_check.status == "missing_total"
    assert result.totals_check.items_sum == 100
    assert result.totals_check.difference is None


def test_no_items_is_not_treated_as_zero_sum_mismatch():
    result = ReceiptParser().parse("ИТОГ 100.00")
    assert result.totals_check.status == "no_items"
    assert result.totals_check.items_sum is None
    assert result.totals_check.difference is None
    assert result.totals_check.item_count == 0


def test_missing_item_amount_is_not_silently_replaced_with_zero():
    from backend.app.parsing.totals import check_receipt_totals

    items = (
        ParsedReceiptItem(raw_name="Известный", total_price=100),
        ParsedReceiptItem(raw_name="Неизвестный"),
    )
    check, warnings = check_receipt_totals(items, Decimal("100.00"))
    assert check.status == "incomplete"
    assert check.items_sum is None
    assert check.difference is None
    assert check.missing_amount_count == 1
    assert warnings


def test_discounts_are_not_subtracted_again_and_zero_price_is_valid():
    from backend.app.parsing.totals import check_receipt_totals

    items = (
        ParsedReceiptItem(
            raw_name="Товар",
            unit_price=100,
            quantity=1,
            total_price=80,
            discount_amount=20,
        ),
        ParsedReceiptItem(raw_name="Подарок", total_price=0),
    )
    check, warnings = check_receipt_totals(items, Decimal("80.00"))
    assert check.status == "matched"
    assert check.items_sum == 80
    assert not warnings


def test_tolerance_can_be_configured_or_set_to_zero():
    raw = "Товар 100.00*1шт=100.00\nИТОГ 100.01"
    assert (
        ReceiptParser(total_tolerance=Decimal(0)).parse(raw).totals_check.status
        == "mismatch"
    )
    assert (
        ReceiptParser(total_tolerance=Decimal("0.01")).parse(raw).totals_check.status
        == "within_tolerance"
    )


@pytest.mark.parametrize("value", ["-0.01", "NaN", "Infinity", "0.001"])
def test_invalid_tolerance_configuration_is_rejected(value):
    with pytest.raises(ValidationError):
        ParsingSettings(_env_file=None, total_tolerance=value)


def test_old_parsing_reports_remain_readable():
    report = ReceiptParsingReport.model_validate(
        {"total_amount": "100.00", "warnings": []}
    )
    assert report.totals_check is None


def test_pipeline_factory_uses_configured_tolerance(monkeypatch):
    from unittest.mock import Mock

    from backend.app.services import receipt_pipeline

    monkeypatch.setattr(receipt_pipeline, "get_object_storage", Mock)
    monkeypatch.setattr(receipt_pipeline, "get_image_orientation_normalizer", Mock)
    monkeypatch.setattr(receipt_pipeline, "get_ocr_provider", Mock)
    monkeypatch.setattr(
        receipt_pipeline.parsing_settings, "total_tolerance", Decimal("0.01")
    )
    result = receipt_pipeline.get_receipt_pipeline().parse(
        "Товар 100.00*1шт=100.00\nИТОГ 100.02"
    )
    assert result.parsed_receipt.totals_check.status == "mismatch"
    assert result.parsed_receipt.totals_check.tolerance == Decimal("0.01")


@pytest.mark.parametrize("number", range(1, 8))
def test_all_reference_receipt_totals_reconcile(number):
    root = Path(__file__).resolve().parents[1] / "fixtures/ocr/v1/texts"
    raw = (root / f"receipt_{number:03}.txt").read_text(encoding="utf-8-sig")
    result = ReceiptParser().parse(raw)
    assert result.totals_check.status == "matched"
    assert result.totals_check.items_sum == result.total_amount
