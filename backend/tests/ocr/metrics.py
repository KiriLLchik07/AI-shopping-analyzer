"""Метрика OCR: игнорируем оформление пробелов и отдельные линии-разделители."""

import re
import unicodedata


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"(?m)^[ \t]*[-─━_=]{3,}[ \t]*$", "", text)
    return " ".join(text.split())


def character_error_rate(expected: str, actual: str) -> float:
    expected, actual = normalize_text(expected), normalize_text(actual)
    if not expected:
        raise ValueError("OCR reference must contain readable text")
    # Levenshtein: insertion, deletion and replacement each cost one character.
    short, long = sorted((expected, actual), key=len)
    previous = list(range(len(short) + 1))
    for row, character in enumerate(long, 1):
        current = [row]
        for column, other in enumerate(short, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (character != other),
                )
            )
        previous = current
    return previous[-1] / len(expected)
