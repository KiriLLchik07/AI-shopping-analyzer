from datetime import UTC, datetime
from decimal import Decimal

import pytest
from backend.app.schemas.parsing import ParsedReceiptItem, ReceiptParsingResult
from pydantic import ValidationError


def test_complete_receipt_preserves_fractional_quantity_and_exact_amounts():
    result = ReceiptParsingResult.model_validate(
        {
            "raw_ocr_text": "Магазин\nЯблоки 0.750 кг 120.00 = 90.00\nИТОГ 90.00\n",
            "store_name": "Магазин",
            "purchase_datetime": "2026-10-20T17:46:00",
            "total_amount": "90.00",
            "items": [
                {
                    "raw_name": "Яблоки",
                    "normalized_name": "яблоки",
                    "quantity": "0.750",
                    "unit": "кг",
                    "unit_price": "120.00",
                    "total_price": "90.00",
                    "discount_amount": "0.00",
                    "confidence": 0.85,
                }
            ],
        }
    )

    assert result.purchase_datetime.isoformat() == "2026-10-20T17:46:00"
    assert result.purchase_datetime.tzinfo is None
    assert result.total_amount == Decimal("90.00")
    item = result.items[0]
    assert isinstance(item, ParsedReceiptItem)
    assert isinstance(item.quantity, Decimal)
    assert item.quantity == Decimal("0.750")
    assert item.unit_price * item.quantity == item.total_price
    assert item.confidence == 0.85
    assert ReceiptParsingResult.model_validate_json(result.model_dump_json()) == result


def test_partial_result_preserves_source_and_does_not_invent_missing_values():
    raw_text = "  МОЛОКО\t\nнечитаемая строка\n"
    raw_name = "  МОЛОКО 3,2%  "
    result = ReceiptParsingResult(
        raw_ocr_text=raw_text,
        items=(ParsedReceiptItem(raw_name=raw_name),),
        warnings=("Не удалось определить дату покупки.",),
    )

    assert result.raw_ocr_text == raw_text
    assert result.store_name is None
    assert result.purchase_datetime is None
    assert result.total_amount is None
    assert result.items[0].model_dump() == {
        "raw_name": raw_name,
        "normalized_name": None,
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "total_price": None,
        "discount_amount": None,
        "confidence": None,
    }
    assert result.warnings == ("Не удалось определить дату покупки.",)


def test_empty_recognition_can_be_represented_without_fake_items():
    result = ReceiptParsingResult(raw_ocr_text="")
    assert result.items == ()
    assert result.warnings == ()


def test_missing_and_zero_amounts_are_distinct():
    item = ParsedReceiptItem(raw_name="Подарок", total_price="0.00")
    assert item.total_price == Decimal("0.00")
    assert item.unit_price is None
    assert ReceiptParsingResult(raw_ocr_text="ИТОГ 0", total_amount=0).total_amount == 0


@pytest.mark.parametrize(
    "field", ["quantity", "unit_price", "total_price", "discount_amount"]
)
@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "-Infinity"])
def test_invalid_item_numeric_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ParsedReceiptItem.model_validate({"raw_name": "Товар", field: value})


def test_zero_quantity_is_rejected():
    with pytest.raises(ValidationError):
        ParsedReceiptItem(raw_name="Товар", quantity=0)


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "-Infinity"])
def test_invalid_receipt_total_is_rejected(value):
    with pytest.raises(ValidationError):
        ReceiptParsingResult(raw_ocr_text="text", total_amount=value)


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_item_confidence_is_rejected(value):
    with pytest.raises(ValidationError):
        ParsedReceiptItem(raw_name="Товар", confidence=value)


@pytest.mark.parametrize("value", [0, 1])
def test_confidence_boundaries_are_valid(value):
    assert ParsedReceiptItem(raw_name="Товар", confidence=value).confidence == value


@pytest.mark.parametrize("field", ["raw_name", "normalized_name", "unit"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_blank_item_text_is_rejected(field, value):
    with pytest.raises(ValidationError):
        ParsedReceiptItem.model_validate({"raw_name": "Товар", field: value})


def test_blank_receipt_fields_and_warnings_are_rejected():
    with pytest.raises(ValidationError):
        ReceiptParsingResult(raw_ocr_text="text", store_name="  ")
    with pytest.raises(ValidationError):
        ReceiptParsingResult(raw_ocr_text="text", warnings=("",))


def test_timezone_is_preserved_without_guessing():
    aware = datetime(2026, 10, 20, 17, 46, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)
    for value in (naive, aware):
        result = ReceiptParsingResult(raw_ocr_text="text", purchase_datetime=value)
        assert result.purchase_datetime == value
        assert result.purchase_datetime.tzinfo == value.tzinfo


def test_totals_mismatch_can_be_reported_without_losing_partial_result():
    result = ReceiptParsingResult(
        raw_ocr_text="text",
        total_amount="200.00",
        items=(ParsedReceiptItem(raw_name="Товар", total_price="100.00"),),
        warnings=("Сумма позиций отличается от итога.",),
    )
    assert result.total_amount == Decimal("200.00")
    assert result.items[0].total_price == Decimal("100.00")
    assert result.warnings


def test_dtos_are_immutable_and_reject_fields_from_other_layers():
    item = ParsedReceiptItem(raw_name="Товар")
    result = ReceiptParsingResult(raw_ocr_text="text", items=(item,))
    with pytest.raises(ValidationError):
        item.raw_name = "Другое"
    with pytest.raises(ValidationError):
        result.items = ()
    with pytest.raises(ValidationError):
        ParsedReceiptItem(raw_name="Товар", category_id="not-a-parser-field")
    with pytest.raises(ValidationError):
        ReceiptParsingResult(raw_ocr_text="text", status="completed")
