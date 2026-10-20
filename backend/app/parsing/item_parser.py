import re
from decimal import Decimal

from backend.app.schemas.parsing import ParsedReceiptItem

NUMBER = r"-?[0-9]+(?:[.,][0-9]+)?"
PRICE = r"(?:[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+|[0-9]+)[.,][0-9]{2}"
UNIT = r"(?:шт\.?|кг\.?|гр\.?|г|мл|л|уп(?:ак)?\.?|WT\.?|Kr)"
MULTIPLY = r"[*×xх]"
CALCULATION = re.compile(
    rf"(?<![\w.,])(?P<price>{PRICE})\s*{MULTIPLY}\s*"
    rf"(?P<quantity>{NUMBER})\s*(?P<unit>{UNIT})?\s*=\s*(?P<total>{PRICE})\s*$",
    re.IGNORECASE,
)
QUANTITY_FIRST = re.compile(
    rf"(?<![\w.,])(?P<quantity>{NUMBER})\s*(?P<unit>{UNIT})\s*{MULTIPLY}\s*"
    rf"(?P<price>{PRICE})\s*=\s*(?P<total>{PRICE})\s*$",
    re.IGNORECASE,
)
CALCULATION_START = re.compile(
    rf"(?<![\w.,]){PRICE}\s*{MULTIPLY}\s*{NUMBER}\s*(?:{UNIT})?\s*$", re.IGNORECASE
)
TABLE_ROW = re.compile(
    rf"(?P<prices>(?:{PRICE}\s+){{0,3}})(?P<quantity>{NUMBER})\s*"
    rf"(?P<unit>{UNIT})?\s+(?P<total>{PRICE})\s*$",
    re.IGNORECASE,
)
TOTAL_ONLY = re.compile(rf"\s*=\s*(?P<total>{PRICE})\s*$")
TABLE_HEADER = re.compile(r"ЦЕНА.*КОЛ.?ВО", re.IGNORECASE)
QUANTITY_HEADER = re.compile(r"КОЛ.?ВО", re.IGNORECASE)
HEADER_TRANSLATION = str.maketrans("ABCEHKMOPTХ", "АВСЕНКМОРТХ")
FOOTER = re.compile(
    r"^(?:ИТОГ|НТОГ\b|ИТО\b|ПОДЫТОГ|К\s+ОПЛАТЕ|СУММА\s+К\s+ОПЛАТЕ|(?:Б|В|6)Е[З3]НАЛИЧ|НАЛИЧ|СДАЧА|СКИДКА\s+ПО\s+КАРТЕ)",
    re.IGNORECASE,
)
SERVICE = re.compile(
    r"^(?:ОНЛАЙН|АТОЛ$|КАССОВЫЙ|М?МАГНИТ$|ПЯТ[ЕЁ]РОЧКА$|МАГАЗИН\b|"
    r"ООО\b|АО\b|ПАО\b|ИП\b|НДС\b|СУММА\s+НДС|ИНН\b|ФН\b|ФД\b|ФП\b|"
    r"РН\b|ЗН\b|КАССИР\b|СНО\b|НОМЕР\b|СКАНИРУЙ|ТЫ\s+МОЖЕШЬ|ТЕЛЕФОНА)",
    re.IGNORECASE,
)
PROMOTION = re.compile(
    r"КУПОН|ЦЕННИК|^(?:АКЦИ[ЯИЮЙ]|СКИДК|ПРИ\s+СЛЕДУЮЩ|БОНУС)", re.IGNORECASE
)
TAX_PREFIX = re.compile(r"^НДС\s+[0-9]+%\s*", re.IGNORECASE)
NUMERIC_FRAGMENT = re.compile(
    rf"(?:{NUMBER}\s*(?:{UNIT})?)(?:\s+{NUMBER}\s*(?:{UNIT})?)*|[*×xх=]", re.IGNORECASE
)


def _decimal(value: str) -> Decimal:
    return Decimal("".join(value.split()).replace(",", "."))


class ReceiptItemParser:
    def parse(
        self, raw_text: str
    ) -> tuple[tuple[ParsedReceiptItem, ...], tuple[str, ...]]:
        items = []
        warnings = []
        names: list[str] = []
        numbers: list[str] = []
        table = False
        header = False
        ambiguous_table = False
        lines = raw_text.splitlines()
        for number, original in enumerate(lines, start=1):
            line = original.strip()
            if not line:
                continue
            structural = line.upper().translate(HEADER_TRANSLATION)
            if TABLE_HEADER.search(structural):
                table = True
                header = False
                ambiguous_table = False
                names.clear()
                numbers.clear()
                continue
            if structural.startswith("ЦЕНА"):
                header = True
                continue
            if QUANTITY_HEADER.fullmatch(structural):
                table = True
                header = True
                continue
            if FOOTER.match(structural):
                if header and not items and not numbers:
                    header = False
                    continue
                following = [
                    value.strip() for value in lines[number:] if value.strip()
                ][:4]
                if (
                    not items
                    and not numbers
                    and any(
                        QUANTITY_HEADER.fullmatch(
                            value.upper().translate(HEADER_TRANSLATION)
                        )
                        for value in following
                    )
                ):
                    table = True
                    continue
                if (
                    not items
                    and names
                    and following
                    and CALCULATION_START.fullmatch(following[0])
                ):
                    continue
                break
            row = TAX_PREFIX.sub("", line) if table else line
            if re.match(r"^(?:НДС|НАС)\b", structural) and (row == line or not row):
                continue
            if self._ignored(row.upper().translate(HEADER_TRANSLATION)):
                names.clear()
                numbers.clear()
                continue
            if ambiguous_table:
                continue
            combined = " ".join([*numbers, row])
            match = self._match(combined, table)
            if match is not None:
                prefix = combined[: match.start()].strip()
                numeric_prefix = "quantity" not in match.groupdict() and (
                    numbers or re.search(MULTIPLY, prefix, re.IGNORECASE)
                )
                if prefix and not numeric_prefix:
                    names.append(prefix)
                item, item_warnings = self._item(names, match, number)
                warnings.extend(item_warnings)
                if item is not None:
                    items.append(item)
                names.clear()
                numbers.clear()
                header = False
            elif partial := CALCULATION_START.search(combined):
                prefix = combined[: partial.start()].strip()
                if prefix:
                    names.append(prefix)
                numbers = [partial.group()]
            elif names and re.search(rf"[0-9].*{MULTIPLY}", row, re.IGNORECASE):
                numbers.append(row)
            elif (table or names) and NUMERIC_FRAGMENT.fullmatch(row):
                numbers.append(row)
                if len(numbers) > 6:
                    warnings.append(f"Строка {number}: числовые колонки не разобраны.")
                    names.clear()
                    numbers.clear()
                    ambiguous_table = table
            elif re.search(r"[а-яёa-z]", row, re.IGNORECASE):
                if numbers:
                    warnings.append(
                        f"Строка {number}: предыдущая товарная строка не разобрана."
                    )
                    names.clear()
                    numbers.clear()
                    ambiguous_table = table
                    if table:
                        continue
                names.append(row)
            else:
                names.clear()
                numbers.clear()
        if numbers:
            if (
                table
                and names
                and re.fullmatch(PRICE, numbers[-1])
                and any(
                    re.search(rf"{NUMBER}\s*{UNIT}", value, re.IGNORECASE)
                    for value in numbers
                )
            ):
                total_match = TOTAL_ONLY.fullmatch("=" + numbers[-1])
                assert total_match is not None
                item, item_warnings = self._item(names, total_match, number)
                if item is not None:
                    items.append(item)
                warnings.extend(item_warnings)
            warnings.append("Последняя товарная строка разобрана не полностью.")
        if not items:
            warnings.append("Товарные строки не найдены.")
        return tuple(items), tuple(warnings)

    @staticmethod
    def _ignored(line: str) -> bool:
        return (
            SERVICE.match(line) is not None
            or PROMOTION.search(line) is not None
            or not re.search(r"[\w]", line)
            or bool(re.search(r"[0-9]{2}[./-][0-9]{2}[./-][0-9]{2}", line))
        )

    @staticmethod
    def _match(line: str, table: bool) -> re.Match | None:
        for pattern in (QUANTITY_FIRST, CALCULATION):
            if match := pattern.search(line):
                return match
        if table:
            for start in re.finditer(r"(?<!\S)-?[0-9]", line):
                prefix = line[: start.start()].strip()
                if prefix and NUMERIC_FRAGMENT.fullmatch(prefix):
                    continue
                match = TABLE_ROW.fullmatch(line, start.start())
                if match is not None and (match["unit"] or match["prices"]):
                    return match
        return TOTAL_ONLY.search(line)

    @staticmethod
    def _item(
        names: list[str], match: re.Match, line_number: int
    ) -> tuple[ParsedReceiptItem | None, list[str]]:
        warnings = []
        name = "\n".join(names)
        if not name or not re.search(r"[а-яёa-z]", name, re.IGNORECASE):
            return None, [f"Строка {line_number}: название товара не найдено."]
        if len(name) > 256:
            return None, [f"Строка {line_number}: название товара слишком длинное."]
        groups = match.groupdict()
        quantity = _decimal(groups["quantity"]) if groups.get("quantity") else None
        if quantity is not None and (
            not 0 < quantity <= Decimal("999999999999.999")
            or quantity != quantity.quantize(Decimal("0.001"))
        ):
            quantity = None
        price = _decimal(groups["price"]) if groups.get("price") else None
        if groups.get("prices"):
            price = _decimal(re.findall(PRICE, groups["prices"])[-1])
        total = _decimal(groups["total"])
        if price is not None and price > Decimal("9999999999.99"):
            price = None
        if total > Decimal("9999999999.99"):
            total = None
        if quantity is None or price is None or total is None:
            warnings.append(
                f"Строка {line_number}: количество, цена или сумма позиции требуют проверки."
            )
        return ParsedReceiptItem(
            raw_name=name,
            quantity=quantity,
            unit=groups.get("unit"),
            unit_price=price,
            total_price=total,
        ), warnings
