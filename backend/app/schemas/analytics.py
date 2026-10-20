import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class AnalyticsPeriod(StrEnum):
    CURRENT_MONTH = "current_month"
    PREVIOUS_MONTH = "previous_month"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    CUSTOM = "custom"


class AnalyticsPeriodParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: AnalyticsPeriod | None = None
    date_from: date | None = Field(
        default=None, description="Начало периода включительно, YYYY-MM-DD."
    )
    date_to: date | None = Field(
        default=None, description="Конец периода включительно, YYYY-MM-DD."
    )
    timezone: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Часовой пояс IANA, например Asia/Omsk.",
    )

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def validate_date_format(cls, value: object) -> object:
        if value is None or (
            isinstance(value, date) and not isinstance(value, datetime)
        ):
            return value
        if isinstance(value, str) and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
        ):
            return value
        raise ValueError("Use a calendar date in YYYY-MM-DD format")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("timezone must be an IANA timezone") from error
        return value

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        has_start = self.date_from is not None
        has_end = self.date_to is not None
        if has_start != has_end:
            raise ValueError("Provide both date_from and date_to")
        if self.period == AnalyticsPeriod.CUSTOM and not has_start:
            raise ValueError("A custom period requires date_from and date_to")
        if self.date_from is not None and self.date_to is not None:
            if self.period not in {None, AnalyticsPeriod.CUSTOM}:
                raise ValueError("Do not combine a preset period with explicit dates")
            if self.date_from > self.date_to:
                raise ValueError("date_from must not be later than date_to")
            if self.date_to == date.max:
                raise ValueError("date_to must be earlier than 9999-12-31")
        return self


class ResolvedAnalyticsPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: AnalyticsPeriod
    date_from: date
    date_to: date
    timezone: str
    start_at: AwareDatetime = Field(
        description="Начало SQL-диапазона в UTC включительно."
    )
    end_at: AwareDatetime = Field(
        description="Конец SQL-диапазона в UTC исключительно."
    )


class ProductSort(StrEnum):
    AMOUNT = "amount"
    FREQUENCY = "frequency"


class TrendGroup(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class AnalyticsLimitParams(AnalyticsPeriodParams):
    limit: int = Field(default=10, ge=1, le=100)


class AnalyticsProductsParams(AnalyticsLimitParams):
    sort_by: ProductSort = ProductSort.AMOUNT


class AnalyticsTrendsParams(AnalyticsPeriodParams):
    group_by: TrendGroup = TrendGroup.DAY


AnalyticsMoney = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
PurchaseCount = Annotated[int, Field(ge=0, description="Количество разных чеков.")]


class AnalyticsSummaryResponse(BaseModel):
    period: ResolvedAnalyticsPeriod
    total_amount: AnalyticsMoney
    purchase_count: PurchaseCount


class CategoryAnalyticsItem(BaseModel):
    category_id: UUID | None
    category_name: str
    total_amount: AnalyticsMoney
    purchase_count: PurchaseCount


class AnalyticsCategoriesResponse(BaseModel):
    period: ResolvedAnalyticsPeriod
    items: list[CategoryAnalyticsItem]


class ProductAnalyticsItem(BaseModel):
    product_name: str
    total_amount: AnalyticsMoney
    purchase_count: PurchaseCount


class AnalyticsProductsResponse(BaseModel):
    period: ResolvedAnalyticsPeriod
    sort_by: ProductSort
    limit: int
    items: list[ProductAnalyticsItem]


class StoreAnalyticsItem(BaseModel):
    store_name: str | None
    total_amount: AnalyticsMoney
    purchase_count: PurchaseCount


class AnalyticsStoresResponse(BaseModel):
    period: ResolvedAnalyticsPeriod
    limit: int
    items: list[StoreAnalyticsItem]


class TrendAnalyticsPoint(BaseModel):
    bucket_start: date = Field(
        description="Начало календарного интервала в выбранном часовом поясе; неделя начинается с понедельника."
    )
    total_amount: AnalyticsMoney
    purchase_count: PurchaseCount


class AnalyticsTrendsResponse(BaseModel):
    period: ResolvedAnalyticsPeriod
    group_by: TrendGroup
    points: list[TrendAnalyticsPoint]
