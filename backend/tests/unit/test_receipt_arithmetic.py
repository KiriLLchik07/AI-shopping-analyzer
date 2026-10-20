from decimal import Decimal

import pytest

from backend.app.core.exceptions import BusinessRuleError
from backend.app.schemas.items import ReceiptItemData
from backend.app.services.receipt_arithmetic import validate_receipt_arithmetic


def item(**values):
    return ReceiptItemData.model_validate(
        {
            "raw_name": "Товар",
            "quantity": "1",
            "unit_price": "100",
            "total_price": "100",
        }
        | values
    )


@pytest.mark.parametrize(
    ("values", "total", "tolerance"),
    [
        ({}, "100", "0"),
        (
            {"quantity": "0.432", "unit_price": "125.50", "total_price": "54.22"},
            "54.22",
            "0",
        ),
        ({"quantity": "0.5", "unit_price": "0.01", "total_price": "0.01"}, "0.01", "0"),
        ({"quantity": "3", "unit_price": "0.10", "total_price": "0.30"}, "0.30", "0"),
        (
            {
                "quantity": "2",
                "unit_price": "40",
                "total_price": "80",
                "discount_amount": "20",
            },
            "80",
            "0",
        ),
        ({"total_price": "100.05"}, "100.05", "0.05"),
        ({"total_price": "99.95"}, "99.95", "0.05"),
        ({}, "100.05", "0.05"),
        ({}, "99.95", "0.05"),
    ],
)
def test_valid_arithmetic(values, total, tolerance):
    validate_receipt_arithmetic(
        [item(**values)], Decimal(total), tolerance=Decimal(tolerance)
    )


@pytest.mark.parametrize(
    ("values", "total"),
    [
        ({"total_price": "100.06"}, "100.06"),
        ({"total_price": "99.94"}, "99.94"),
        ({}, "100.06"),
        ({}, "99.94"),
        (
            {
                "quantity": "2",
                "unit_price": "40",
                "total_price": "60",
                "discount_amount": "20",
            },
            "60",
        ),
        ({"quantity": None}, "100"),
        ({"unit_price": None}, "100"),
        ({"total_price": None}, "100"),
    ],
)
def test_invalid_or_incomplete_arithmetic(values, total):
    with pytest.raises(BusinessRuleError):
        validate_receipt_arithmetic(
            [item(**values)], Decimal(total), tolerance=Decimal("0.05")
        )


@pytest.mark.parametrize(
    "total", [None, Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")]
)
def test_invalid_receipt_total(total):
    with pytest.raises(BusinessRuleError):
        validate_receipt_arithmetic([item()], total, tolerance=Decimal("0.05"))


def test_empty_receipt_cannot_be_confirmed():
    with pytest.raises(BusinessRuleError):
        validate_receipt_arithmetic([], Decimal(100), tolerance=Decimal("0.05"))


def test_sum_includes_free_items_and_does_not_subtract_discounts_again():
    validate_receipt_arithmetic(
        [item(discount_amount="10"), item(unit_price="0", total_price="0")],
        Decimal(100),
        tolerance=Decimal(0),
    )


@pytest.mark.parametrize(
    "tolerance", [Decimal(-1), Decimal("NaN"), Decimal("Infinity")]
)
def test_invalid_tolerance_is_configuration_error(tolerance):
    with pytest.raises(ValueError):
        validate_receipt_arithmetic([item()], Decimal(100), tolerance=tolerance)
