import math
from collections.abc import Iterable, Mapping

from backend.app.schemas.ocr import OcrResult


def ocr_line_confidences(result: OcrResult) -> dict[int, float]:
    spans = []
    offset = 0
    for part in result.fragments:
        end = offset + len(part.text)
        spans.append((offset, end, part.confidence))
        offset = end + 1

    scores = {}
    offset = 0
    cursor = 0
    for number, line in enumerate(result.raw_text.splitlines(keepends=True), start=1):
        end = offset + len(line.rstrip("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"))
        while cursor < len(spans) and spans[cursor][1] <= offset:
            cursor += 1
        current = cursor
        included = []
        while current < len(spans) and spans[current][0] < end:
            included.append(spans[current][2])
            current += 1
        if line.strip() and included:
            scores[number] = min(included)
        offset += len(line)
    return scores


def item_ocr_confidence(
    source_lines: Iterable[int], line_confidences: Mapping[int, float] | None
) -> float | None:
    if line_confidences is None:
        return None
    scores = []
    for number in source_lines:
        score = line_confidences.get(number)
        if score is None:
            return None
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid OCR line confidence")
        scores.append(score)
    return min(scores) if scores else None
