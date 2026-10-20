from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ItemQuantity = Annotated[
    Decimal, Field(gt=0, max_digits=15, decimal_places=3, allow_inf_nan=False)
]
ItemAmount = Annotated[
    Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
]


class ReceiptItemData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    raw_name: str = Field(min_length=1, max_length=256)
    normalized_name: str | None = Field(default=None, max_length=256)
    category_id: UUID | None = None
    quantity: ItemQuantity | None = None
    unit: str | None = Field(default=None, max_length=100)
    weight: Decimal | None = Field(default=None, gt=0)
    unit_price: ItemAmount | None = None
    total_price: ItemAmount | None = None
    discount_amount: ItemAmount = Decimal("0.00")
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    is_impulse_candidate: bool = False
