from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.app.schemas.analytics import AnalyticsPeriodParams

Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, decimal_places=2)]
Count = Annotated[int, Field(ge=0, strict=True)]
RuleText = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=2000
    ),
]


class ReportDto(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always"
    )


class MonthlyReportParams(ReportDto):
    month: date
    timezone: str | None = None

    @field_validator("month", mode="before")
    @classmethod
    def validate_month_format(cls, value: object) -> object:
        return AnalyticsPeriodParams.validate_date_format(value)

    @field_validator("month")
    @classmethod
    def validate_month(cls, value: date) -> date:
        if value.day != 1 or value <= date(1, 1, 1) or value >= date(9999, 12, 1):
            raise ValueError(
                "month must be the first day of a supported calendar month"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return AnalyticsPeriodParams.validate_timezone(value)


class MonthlyTotals(ReportDto):
    date_from: date
    date_to: date
    total_amount: Money
    purchase_count: Count

    @model_validator(mode="after")
    def validate_calendar_month(self) -> Self:
        last = monthrange(self.date_from.year, self.date_from.month)[1]
        if self.date_from.day != 1 or self.date_to != self.date_from.replace(day=last):
            raise ValueError("Totals must describe one complete calendar month")
        return self


class ReportCategory(ReportDto):
    category_name: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ]
    total_amount: Money
    purchase_count: Count


class ReportWeek(ReportDto):
    bucket_start: date
    total_amount: Money
    purchase_count: Count


class MonthlyReportData(ReportDto):
    schema_version: Literal["monthly-input-v1"] = "monthly-input-v1"
    currency: Literal["RUB"] = "RUB"
    timezone: str
    current: MonthlyTotals
    previous: MonthlyTotals
    categories: tuple[ReportCategory, ...]
    weekly_trends: tuple[ReportWeek, ...] = Field(max_length=6)
    rules: tuple[RuleText, ...] = Field(max_length=20)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        AnalyticsPeriodParams.validate_timezone(value)
        return value

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        if self.current.date_from <= date(1, 1, 1):
            raise ValueError("Previous month is outside the supported date range")
        if self.previous.date_to != self.current.date_from - timedelta(days=1):
            raise ValueError("Comparison must use the immediately preceding month")
        return self


class ReportRecommendation(ReportDto):
    title: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=160
        ),
    ]
    reason: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=1000
        ),
    ]
    action: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=1000
        ),
    ]


class MonthlyReportResult(ReportDto):
    schema_version: Literal["monthly-report-v1"]
    summary: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=2000
        ),
    ]
    recommendations: tuple[ReportRecommendation, ...] = Field(
        min_length=3, max_length=5
    )
