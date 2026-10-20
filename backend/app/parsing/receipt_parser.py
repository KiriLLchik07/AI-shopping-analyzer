import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.parsing.formats import DATE, MONEY, decimal_number
from backend.app.parsing.item_parser import ReceiptItemParser
from backend.app.parsing.totals import check_receipt_totals
from backend.app.schemas.parsing import ReceiptParsingResult

TOTAL_LABEL = re.compile(
    r"^(?:ИТОГ(?:О)?(?:\s+К\s+ОПЛАТЕ)?|(?:СУММА\s+)?К\s+ОПЛАТЕ)\b",
    re.IGNORECASE,
)
TIME = re.compile(
    r"(?<![\d:])(?P<time>[0-9]{2}:[0-9]{2}(?::[0-9]{2})?)"
    r"(?:\s*(?P<offset>Z|[+-][0-9]{2}:[0-9]{2}))?(?![\d:])"
)
PROMOTION = re.compile(
    r"АКЦИ|КУПОН|СКИДК|ДЕЙСТВУЕТ|СЛЕДУЮЩ|ГОДЕН|СРОК|ИЗГОТОВ|ПО\s+\d|ДО\s+\d",
    re.IGNORECASE,
)
BRAND = re.compile(
    r"МАГНИТ|ПЯТ[ЕЁ]РОЧКА|ПЕРЕКР[ЕЁ]СТОК|ЛЕНТА|АШАН|ДИКСИ|ВКУСВИЛЛ|МЕТРО|METRO",
    re.IGNORECASE,
)
MERCHANT = re.compile(
    r"^(?:(?:ООО|ПАО|ОАО|ЗАО|АО|ИП)\s+\S.+|МАГАЗИН\s+\S.+)$", re.IGNORECASE
)
MAX_AMOUNT = Decimal("9999999999.99")


def _lines(raw_text: str) -> list[str]:
    return [" ".join(line.split()) for line in raw_text.splitlines() if line.strip()]


def _unique[T](values: list[T]) -> list[T]:
    return list(dict.fromkeys(values))


class ReceiptParser:
    def __init__(
        self,
        timezone: str | None = None,
        total_tolerance: Decimal = Decimal("0.05"),
    ) -> None:
        self.timezone = ZoneInfo(timezone) if timezone is not None else None
        self.total_tolerance = total_tolerance

    def parse(
        self, raw_text: str, *, line_confidences: Mapping[int, float] | None = None
    ) -> ReceiptParsingResult:
        lines = _lines(raw_text)
        store, store_warnings = self._store(lines)
        purchased_at, date_warnings = self._datetime(lines)
        total, total_warnings = self._total(lines)
        items, item_warnings = ReceiptItemParser().parse(
            raw_text, line_confidences=line_confidences
        )
        totals_check, check_warnings = check_receipt_totals(
            items, total, tolerance=self.total_tolerance
        )
        return ReceiptParsingResult(
            raw_ocr_text=raw_text,
            store_name=store,
            purchase_datetime=purchased_at,
            total_amount=total,
            items=items,
            warnings=(
                *store_warnings,
                *date_warnings,
                *total_warnings,
                *item_warnings,
                *check_warnings,
            ),
            totals_check=totals_check,
            item_confidence_method="min_ocr_fragment_v1" if line_confidences else None,
        )

    def _store(self, lines: list[str]) -> tuple[str | None, tuple[str, ...]]:
        brands = [line for line in lines if BRAND.fullmatch(line)]
        matches = brands or [line for line in lines if MERCHANT.fullmatch(line)]
        candidates_by_name = {}
        for name in matches:
            candidates_by_name.setdefault(name.casefold().replace("ё", "е"), name)
        candidates = list(candidates_by_name.values())
        if len(candidates) != 1:
            return None, ("Магазин не найден или определён неоднозначно.",)
        if len(candidates[0]) > 100:
            return None, ("Название магазина превышает допустимую длину.",)
        return candidates[0], ()

    def _total(self, lines: list[str]) -> tuple[Decimal | None, tuple[str, ...]]:
        amounts = []
        for index, line in enumerate(lines):
            label = TOTAL_LABEL.match(line)
            if label is None:
                continue
            tail = line[label.end() :].strip(" :=")
            if not tail and index + 1 < len(lines):
                tail = lines[index + 1]
            match = MONEY.fullmatch(tail)
            if match is None:
                continue
            value = decimal_number(match["amount"])
            amounts.append(value)
        candidates = _unique(amounts)
        if len(candidates) != 1:
            return None, ("Итоговая сумма не найдена или определена неоднозначно.",)
        if not 0 < candidates[0] <= MAX_AMOUNT:
            return None, ("Итоговая сумма вне поддерживаемого диапазона.",)
        return candidates[0], ()

    def _datetime(self, lines: list[str]) -> tuple[datetime | None, tuple[str, ...]]:
        candidates = []
        for index, line in enumerate(lines):
            if PROMOTION.search(line):
                continue
            dates = list(DATE.finditer(line))
            if len(dates) != 1:
                continue
            date_match = dates[0]
            time_matches = list(TIME.finditer(line[date_match.end() :]))
            if not time_matches and index + 1 < len(lines):
                next_line = lines[index + 1]
                if re.fullmatch(
                    r"(?:ВРЕМЯ\s*:?\s*)?" + TIME.pattern, next_line, re.IGNORECASE
                ):
                    time_matches = list(TIME.finditer(next_line))
            if len(time_matches) != 1:
                continue
            value = self._parse_datetime(date_match["date"], time_matches[0])
            if value is not None:
                candidates.append(value)
        candidates = _unique(candidates)
        if len(candidates) != 1:
            return None, (
                "Дата и время покупки не найдены или определены неоднозначно.",
            )
        value = candidates[0]
        if value.tzinfo is not None:
            return value, ()
        if self.timezone is None:
            return value, (
                "Время покупки местное: задайте PARSING_TIMEZONE для записи в поле даты БД.",
            )
        localized = value.replace(tzinfo=self.timezone)
        alternative = localized.replace(fold=1)
        if (
            localized.utcoffset() != alternative.utcoffset()
            or localized.astimezone(UTC).astimezone(self.timezone).replace(tzinfo=None)
            != value
        ):
            return value, ("Время покупки неоднозначно из-за перевода часов.",)
        return localized, ()

    @staticmethod
    def _parse_datetime(date_text: str, time_match: re.Match) -> datetime | None:
        parts = re.split(r"[./-]", date_text)
        if len(parts[0]) == 4:
            year, month, day = (int(part) for part in parts)
        else:
            day, month, year = (int(part) for part in parts)
            if len(parts[2]) == 2:
                year += 2000
        try:
            date_value = f"{year:04}-{month:02}-{day:02}"
            offset = time_match["offset"] or ""
            return datetime.fromisoformat(f"{date_value}T{time_match['time']}{offset}")
        except ValueError:
            return None
