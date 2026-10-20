from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

NonBlankText = Annotated[str, Field(min_length=1, pattern=r"\S")]
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ParsedReceiptItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_name: NonBlankText
    normalized_name: NonBlankText | None = None
    quantity: Quantity | None = None
    unit: NonBlankText | None = None
    unit_price: Amount | None = None
    total_price: Amount | None = None
    discount_amount: Amount | None = None
    confidence: Confidence | None = None


class TotalsCheckStatus(StrEnum):
    MATCHED = "matched"
    WITHIN_TOLERANCE = "within_tolerance"
    MISMATCH = "mismatch"
    INCOMPLETE = "incomplete"
    MISSING_TOTAL = "missing_total"
    NO_ITEMS = "no_items"


class ReceiptTotalsCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: TotalsCheckStatus
    items_sum: Amount | None
    difference: Decimal | None = Field(allow_inf_nan=False)
    tolerance: Amount
    item_count: int = Field(ge=0)
    missing_amount_count: int = Field(ge=0)


class ReceiptParsingReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    store_name: NonBlankText | None = None
    purchase_datetime: datetime | None = None
    total_amount: Amount | None = None
    warnings: tuple[NonBlankText, ...] = ()
    totals_check: ReceiptTotalsCheck | None = None


class ReceiptParsingResult(ReceiptParsingReport):
    raw_ocr_text: str
    items: tuple[ParsedReceiptItem, ...] = ()
