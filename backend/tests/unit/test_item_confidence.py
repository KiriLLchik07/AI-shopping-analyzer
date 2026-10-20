from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.app.schemas.ocr import OcrResult
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline


def ocr_result(parts, overall=0.01):
    return OcrResult.model_validate(
        {
            "raw_text": "\n".join(text for text, _ in parts),
            "confidence": overall,
            "fragments": [{"text": text, "confidence": score} for text, score in parts],
        }
    )


def process(parts):
    return UnconfiguredReceiptPipeline(Mock(), Mock()).parse_with_metadata(
        ocr_result(parts)
    )


def test_identical_product_names_use_their_own_fragment_scores_not_overall_score():
    result = process(
        [
            ("Молоко", 0.95),
            ("100.00*1шт=100.00", 0.9),
            ("Молоко", 0.65),
            ("100.00*1шт=100.00", 0.8),
            ("ИТОГ 200.00", 0.1),
        ]
    )
    assert [item.confidence for item in result.items] == [0.9, 0.65]
    assert [item.confidence for item in result.parsed_receipt.items] == [0.9, 0.65]
    assert result.parsed_receipt.item_confidence_method == "min_ocr_fragment_v1"


def test_wrapped_names_include_all_name_fragments_and_ignore_tax_and_footer():
    result = process(
        [
            ("ОНЛАЙН-КАССА", 0.01),
            ("Салат с говяжьим языком", 0.98),
            ("и майонезом", 0.81),
            ("100.00*1шт", 0.93),
            ("НДС не облагается", 0.02),
            ("=100.00", 0.9),
            ("ИТОГ 100.00", 0.03),
        ]
    )
    assert result.items[0].confidence == 0.81
    assert result.items[0].raw_name == "Салат с говяжьим языком\nи майонезом"


def test_table_sources_do_not_include_header_or_previous_item():
    result = process(
        [
            ("Цена Кол-во ИТОГ", 0.01),
            ("Первый", 0.7),
            ("100.00", 0.8),
            ("1шт", 0.9),
            ("100.00", 0.75),
            ("Второй", 0.92),
            ("200.00", 0.95),
            ("1шт", 0.99),
            ("200.00", 0.96),
            ("ИТОГ 300.00", 0.03),
        ]
    )
    assert [item.confidence for item in result.items] == [0.7, 0.92]


@pytest.mark.parametrize("breaks", ["\n", "\r\n", "\n\n"])
def test_multiline_fragment_scores_are_aligned_to_parser_line_numbers(breaks):
    result = process(
        [(f"Молоко{breaks}100.00*1шт=100.00", 0.83), ("ИТОГ 100.00", 0.01)]
    )
    assert result.items[0].confidence == 0.83


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_confidence_boundaries_are_preserved(score):
    result = process([("Товар 100.00*1шт=100.00", score), ("ИТОГ 100.00", 0.5)])
    assert result.items[0].confidence == score


def test_legacy_ocr_without_fragments_does_not_copy_receipt_confidence_to_items():
    result = UnconfiguredReceiptPipeline(Mock(), Mock()).parse_with_metadata(
        OcrResult(raw_text="Товар 100.00*1шт=100.00\nИТОГ 100.00", confidence=0.99)
    )
    assert result.items[0].confidence is None
    assert result.parsed_receipt.item_confidence_method is None


def test_partial_item_still_has_ocr_confidence_but_keeps_parsing_warning():
    result = process([("Товар =100.00", 0.98), ("ИТОГ 100.00", 0.7)])
    assert result.items[0].confidence == 0.98
    assert result.items[0].quantity is None
    assert result.items[0].unit_price is None
    assert any(
        "требуют проверки" in warning for warning in result.parsed_receipt.warnings
    )


def test_incomplete_source_scores_do_not_create_fake_confidence():
    from backend.app.parsing.receipt_parser import ReceiptParser

    result = ReceiptParser().parse(
        "Товар\n100.00*1шт=100.00\nИТОГ 100.00", line_confidences={1: 0.9}
    )
    assert result.items[0].confidence is None


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_fragment_confidence_is_rejected(score):
    with pytest.raises(ValidationError):
        ocr_result([("Товар", score)])


def test_fragments_cannot_be_attached_to_different_ocr_text():
    with pytest.raises(ValidationError):
        OcrResult.model_validate(
            {
                "raw_text": "Другой текст",
                "fragments": [{"text": "Товар", "confidence": 0.9}],
            }
        )


def test_fragment_with_trailing_line_break_does_not_shift_next_fragment_score():
    result = process(
        [
            ("Первый 10.00*1шт=10.00\n", 0.95),
            ("Второй 20.00*1шт=20.00", 0.72),
            ("ИТОГ 30.00", 0.01),
        ]
    )
    assert [item.confidence for item in result.items] == [0.95, 0.72]


def test_partial_table_fallback_uses_numeric_sources_not_footer():
    result = process(
        [
            ("Цена Кол-во ИТОГ", 0.01),
            ("Бананы", 0.95),
            ("169.99", 0.91),
            ("169.99", 0.9),
            ("3 0.432Kr", 0.73),
            ("73.44", 0.88),
            ("ИТОГ 73.44", 0.02),
        ]
    )
    assert result.items[0].raw_name == "Бананы"
    assert result.items[0].confidence == 0.73
    assert result.items[0].quantity is None


def test_discarded_numeric_sources_do_not_affect_next_valid_item():
    result = process(
        [
            ("Черновая строка", 0.01),
            ("100.00", 0.02),
            ("Следующий товар", 0.93),
            ("50.00*1шт=50.00", 0.91),
            ("ИТОГ 50.00", 0.1),
        ]
    )
    assert result.items[0].raw_name == "Следующий товар"
    assert result.items[0].confidence == 0.91
