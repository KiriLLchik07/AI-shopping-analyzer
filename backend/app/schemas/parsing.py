from datetime import datetime
from decimal import Decimal
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


class ReceiptParsingReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    store_name: NonBlankText | None = None
    purchase_datetime: datetime | None = None
    total_amount: Amount | None = None
    warnings: tuple[NonBlankText, ...] = ()


class ReceiptParsingResult(ReceiptParsingReport):
    raw_ocr_text: str
    items: tuple[ParsedReceiptItem, ...] = ()
