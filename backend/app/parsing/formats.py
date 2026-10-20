import re
from decimal import Decimal

WHOLE_AMOUNT = r"(?:[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+|[0-9]+)"
RUBLE = r"(?:₽|руб(?:лей|ля|\.)?|р\.|RUB)"
AMOUNT = rf"{WHOLE_AMOUNT}(?:[.,][0-9]{{1,2}})?"
PRICE = (
    rf"(?:{WHOLE_AMOUNT}[.,][0-9]{{1,2}}(?:\s*{RUBLE})?"
    rf"|{WHOLE_AMOUNT}\s*{RUBLE})"
)
MONEY = re.compile(rf"[:=\s]*(?P<amount>{AMOUNT})\s*(?:{RUBLE})?", re.IGNORECASE)
CURRENCY = re.compile(RUBLE, re.IGNORECASE)
DATE = re.compile(
    r"(?<![\d./-])(?P<date>[0-9]{4}(?P<year_separator>[./-])"
    r"[0-9]{1,2}(?P=year_separator)[0-9]{1,2}"
    r"|[0-9]{1,2}(?P<separator>[./-])[0-9]{1,2}(?P=separator)(?:[0-9]{4}|[0-9]{2}))"
    r"(?![\d./-])"
)


def decimal_number(value: str) -> Decimal:
    return Decimal("".join(value.split()).replace(",", "."))


def money_value(value: str) -> Decimal:
    match = MONEY.fullmatch(value)
    if match is None:
        raise ValueError("Unsupported monetary value")
    return decimal_number(match["amount"])
