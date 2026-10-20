from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.core.config import AnalyticsSettings
from backend.app.schemas.analytics import AnalyticsMonthComparisonParams
from backend.app.services.analytics_period_service import (
    resolve_month_comparison_periods,
)
from backend.app.services.analytics_service import _percentage_change


def resolve(now, timezone="Asia/Omsk", max_days=366):
    return resolve_month_comparison_periods(
        AnalyticsMonthComparisonParams(timezone=timezone),
        AnalyticsSettings(_env_file=None, timezone=timezone, max_period_days=max_days),
        now=now,
    )


def test_comparison_uses_same_local_day_and_clock_in_both_months():
    result = resolve(datetime(2026, 10, 20, 12, tzinfo=UTC))
    assert result.current_start == datetime(2026, 9, 30, 18, tzinfo=UTC)
    assert result.current_end == result.as_of == datetime(2026, 10, 20, 12, tzinfo=UTC)
    assert result.previous_start == datetime(2026, 8, 31, 18, tzinfo=UTC)
    assert result.previous_end == datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        (
            datetime(2026, 1, 15, 12, tzinfo=UTC),
            datetime(2025, 12, 1, tzinfo=UTC),
            datetime(2025, 12, 15, 12, tzinfo=UTC),
        ),
        (
            datetime(2026, 3, 31, 12, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            datetime(2026, 3, 1, tzinfo=UTC),
        ),
        (
            datetime(2024, 3, 30, 12, tzinfo=UTC),
            datetime(2024, 2, 1, tzinfo=UTC),
            datetime(2024, 3, 1, tzinfo=UTC),
        ),
        (
            datetime(2026, 5, 31, 12, tzinfo=UTC),
            datetime(2026, 4, 1, tzinfo=UTC),
            datetime(2026, 5, 1, tzinfo=UTC),
        ),
        (
            datetime(2024, 2, 29, 12, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 29, 12, tzinfo=UTC),
        ),
    ],
)
def test_year_transition_and_shorter_previous_month(now, start, end):
    result = resolve(now, timezone="UTC")
    assert result.previous_start == start
    assert result.previous_end == end


def test_month_selection_uses_requested_timezone():
    now = datetime(2026, 10, 31, 20, tzinfo=UTC)
    assert resolve(now).current_start == datetime(2026, 10, 31, 18, tzinfo=UTC)
    assert resolve(now, "UTC").current_start == datetime(2026, 10, 1, tzinfo=UTC)


def test_dst_uses_local_clock_not_fixed_utc_offset():
    result = resolve(datetime(2026, 3, 15, 12, tzinfo=UTC), "America/New_York")
    assert result.current_start == datetime(2026, 3, 1, 5, tzinfo=UTC)
    assert result.previous_start == datetime(2026, 2, 1, 5, tzinfo=UTC)
    assert result.previous_end == datetime(2026, 2, 15, 13, tzinfo=UTC)


def test_at_month_start_both_windows_are_empty():
    result = resolve(datetime(2026, 10, 1, tzinfo=UTC), "UTC")
    assert result.current_start == result.current_end
    assert result.previous_start == result.previous_end


def test_comparison_respects_maximum_period_size():
    with pytest.raises(ValueError, match="7 calendar days"):
        resolve(datetime(2026, 10, 20, 12, tzinfo=UTC), max_days=7)


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="must include a timezone"):
        resolve(datetime(2026, 10, 20, tzinfo=UTC).replace(tzinfo=None))


def test_datetime_underflow_is_a_validation_error():
    with pytest.raises(ValueError, match="outside the supported"):
        resolve(datetime(1, 1, 1, tzinfo=UTC), "UTC")


@pytest.mark.parametrize(
    "params",
    [
        {"timezone": "invalid"},
        {"date_from": "2026-01-01"},
        {"period": "previous_month"},
    ],
)
def test_comparison_only_accepts_valid_timezone(params):
    with pytest.raises(ValidationError):
        AnalyticsMonthComparisonParams.model_validate(params)


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ("150", "75", "100.00"),
        ("75", "150", "-50.00"),
        ("1", "3", "-66.67"),
        ("4", "3", "33.33"),
        ("0", "100", "-100.00"),
        ("100", "100", "0.00"),
        ("0", "0", "0.00"),
        ("100", "0", None),
    ],
)
def test_percentage_change_has_defined_zero_baseline_behavior(
    current, previous, expected
):
    actual = _percentage_change(Decimal(current), Decimal(previous))
    assert actual == (Decimal(expected) if expected is not None else None)
