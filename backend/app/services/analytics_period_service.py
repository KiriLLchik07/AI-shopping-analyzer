from calendar import monthrange
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.app.core.config import AnalyticsSettings
from backend.app.schemas.analytics import (
    AnalyticsMonthComparisonParams,
    AnalyticsPeriod,
    AnalyticsPeriodParams,
    MonthComparisonPeriods,
    ResolvedAnalyticsPeriod,
)


def resolve_analytics_period(
    params: AnalyticsPeriodParams,
    settings: AnalyticsSettings,
    *,
    now: datetime | None = None,
) -> ResolvedAnalyticsPeriod:
    clock = now if now is not None else datetime.now(UTC)
    if clock.utcoffset() is None:
        raise ValueError("The current time must include a timezone")
    timezone = params.timezone or settings.timezone
    zone = ZoneInfo(timezone)
    today = clock.astimezone(zone).date()
    period = params.period or (
        AnalyticsPeriod.CUSTOM
        if params.date_from is not None
        else AnalyticsPeriod.CURRENT_MONTH
    )
    try:
        if period == AnalyticsPeriod.CUSTOM:
            start, end = params.date_from, params.date_to
            if start is None or end is None:
                raise ValueError("A custom period requires date_from and date_to")
        elif period in {AnalyticsPeriod.LAST_7_DAYS, AnalyticsPeriod.LAST_30_DAYS}:
            days = 7 if period == AnalyticsPeriod.LAST_7_DAYS else 30
            start, end = today - timedelta(days=days - 1), today
        else:
            start = today.replace(day=1)
            if period == AnalyticsPeriod.PREVIOUS_MONTH:
                start = (start - timedelta(days=1)).replace(day=1)
            end = start.replace(day=monthrange(start.year, start.month)[1])
        if (end - start).days + 1 > settings.max_period_days:
            raise ValueError(
                f"Period must not exceed {settings.max_period_days} calendar days"
            )
        start_at = datetime.combine(start, time.min, zone).astimezone(UTC)
        end_at = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(
            UTC
        )
    except OverflowError as error:
        raise ValueError(
            "Period boundaries are outside the supported datetime range"
        ) from error
    if end_at <= start_at:
        raise ValueError("Period contains no existing time in the selected timezone")
    return ResolvedAnalyticsPeriod(
        period=period,
        date_from=start,
        date_to=end,
        timezone=timezone,
        start_at=start_at,
        end_at=end_at,
    )


def resolve_month_comparison_periods(
    params: AnalyticsMonthComparisonParams,
    settings: AnalyticsSettings,
    *,
    now: datetime | None = None,
) -> MonthComparisonPeriods:
    clock = now if now is not None else datetime.now(UTC)
    if clock.utcoffset() is None:
        raise ValueError("The current time must include a timezone")
    timezone = params.timezone or settings.timezone
    zone = ZoneInfo(timezone)
    try:
        local = clock.astimezone(zone)
        current_start = datetime.combine(local.date().replace(day=1), time.min, zone)
        previous_date = (current_start.date() - timedelta(days=1)).replace(day=1)
        previous_start = datetime.combine(previous_date, time.min, zone)
        if local.day > monthrange(previous_date.year, previous_date.month)[1]:
            previous_end = current_start
        else:
            previous_end = datetime.combine(
                previous_date.replace(day=local.day), local.time(), zone
            )
        for start, end in ((current_start, local), (previous_start, previous_end)):
            days = (end.date() - start.date()).days + (end.time() != time.min)
            if days > settings.max_period_days:
                raise ValueError(
                    f"Period must not exceed {settings.max_period_days} calendar days"
                )
        return MonthComparisonPeriods(
            timezone=timezone,
            as_of=clock.astimezone(UTC),
            current_start=current_start.astimezone(UTC),
            current_end=clock.astimezone(UTC),
            previous_start=previous_start.astimezone(UTC),
            previous_end=previous_end.astimezone(UTC),
        )
    except OverflowError as error:
        raise ValueError(
            "Period boundaries are outside the supported datetime range"
        ) from error
