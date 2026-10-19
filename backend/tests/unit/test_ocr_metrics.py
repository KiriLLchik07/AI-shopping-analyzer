import pytest

from backend.tests.ocr.metrics import character_error_rate, normalize_text


@pytest.mark.parametrize(
    ("actual", "expected_error"),
    [
        ("молоко", 0),
        ("малако", 2 / 6),
        ("молок", 1 / 6),
        ("молокоо", 1 / 6),
        ("", 1),
        ("МОЛОКО", 1),
    ],
)
def test_cer_counts_recognition_errors(actual, expected_error):
    assert character_error_rate("молоко", actual) == pytest.approx(expected_error)


def test_normalization_ignores_layout_but_keeps_numbers_punctuation_and_ascii_art():
    assert normalize_text("  ИТОГ\t100.00\n------\n@@ @@\n") == "ИТОГ 100.00 @@ @@"
    assert character_error_rate("ИТОГ\n 100.00", "ИТОГ 100.00") == 0
    assert character_error_rate("100.00", "10000") > 0
    assert character_error_rate("@@@", "20%") > 0
    assert normalize_text("е\u0308") == "ё"


def test_empty_reference_is_rejected():
    with pytest.raises(ValueError, match="reference"):
        character_error_rate(" \n---\n", "text")
