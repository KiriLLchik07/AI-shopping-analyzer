from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.dependencies import analytics as dependency
from backend.app.core.config import AnalyticsSettings
from backend.app.schemas.analytics import AnalyticsPeriodParams, ResolvedAnalyticsPeriod
from backend.app.services.analytics_period_service import resolve_analytics_period

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def settings(**values):
    return AnalyticsSettings(
        _env_file=None, **({"timezone": "Asia/Omsk", "max_period_days": 366} | values)
    )


def resolve(params=None, *, now=NOW, **config):
    return resolve_analytics_period(
        AnalyticsPeriodParams.model_validate(params or {}), settings(**config), now=now
    )


@pytest.mark.parametrize(
    ("params", "expected_period", "start", "end"),
    [
        ({}, "current_month", "2026-10-01", "2026-10-31"),
        ({"period": "current_month"}, "current_month", "2026-10-01", "2026-10-31"),
        ({"period": "previous_month"}, "previous_month", "2026-09-01", "2026-09-30"),
        ({"period": "last_7_days"}, "last_7_days", "2026-10-14", "2026-10-20"),
        ({"period": "last_30_days"}, "last_30_days", "2026-09-21", "2026-10-20"),
        (
            {"date_from": "2026-10-01", "date_to": "2026-10-20"},
            "custom",
            "2026-10-01",
            "2026-10-20",
        ),
        (
            {"period": "custom", "date_from": "2026-10-20", "date_to": "2026-10-20"},
            "custom",
            "2026-10-20",
            "2026-10-20",
        ),
    ],
)
def test_period_selection(params, expected_period, start, end):
    result = resolve(params)
    assert result.period == expected_period
    assert result.date_from == date.fromisoformat(start)
    assert result.date_to == date.fromisoformat(end)
    assert result.timezone == "Asia/Omsk"
    assert result.start_at.utcoffset() == result.end_at.utcoffset() == timedelta(0)


def test_inclusive_last_day_becomes_exclusive_utc_boundary():
    result = resolve({"date_from": "2026-10-20", "date_to": "2026-10-20"})
    assert result.start_at == datetime(2026, 10, 19, 18, tzinfo=UTC)
    assert result.end_at == datetime(2026, 10, 20, 18, tzinfo=UTC)
    assert (
        result.start_at
        <= datetime(2026, 10, 20, 17, 59, 59, 999999, tzinfo=UTC)
        < result.end_at
    )


@pytest.mark.parametrize(
    ("period", "now", "start", "end"),
    [
        (
            "previous_month",
            datetime(2026, 1, 10, tzinfo=UTC),
            date(2025, 12, 1),
            date(2025, 12, 31),
        ),
        (
            "previous_month",
            datetime(2024, 3, 10, tzinfo=UTC),
            date(2024, 2, 1),
            date(2024, 2, 29),
        ),
        (
            "current_month",
            datetime(2024, 2, 10, tzinfo=UTC),
            date(2024, 2, 1),
            date(2024, 2, 29),
        ),
        (
            "last_7_days",
            datetime(2026, 1, 3, tzinfo=UTC),
            date(2025, 12, 28),
            date(2026, 1, 3),
        ),
    ],
)
def test_year_and_leap_day_boundaries(period, now, start, end):
    result = resolve({"period": period}, now=now)
    assert (result.date_from, result.date_to) == (start, end)


def test_today_is_computed_in_selected_timezone():
    now = datetime(2026, 10, 31, 20, tzinfo=UTC)
    omsk = resolve(now=now)
    utc = resolve({"timezone": "UTC"}, now=now)
    assert omsk.date_from == date(2026, 11, 1)
    assert utc.date_from == date(2026, 10, 1)


@pytest.mark.parametrize(("day", "hours"), [("2026-03-08", 23), ("2026-11-01", 25)])
def test_dst_days_use_local_midnights_instead_of_fixed_24_hours(day, hours):
    result = resolve({"date_from": day, "date_to": day, "timezone": "America/New_York"})
    assert result.end_at - result.start_at == timedelta(hours=hours)


def test_limit_counts_calendar_days_inclusively():
    assert resolve(
        {"date_from": "2024-01-01", "date_to": "2024-12-31"}
    ).date_to == date(2024, 12, 31)
    with pytest.raises(ValueError, match="366 calendar days"):
        resolve({"date_from": "2024-01-01", "date_to": "2025-01-01"})
    assert resolve(
        {"date_from": "2024-01-01", "date_to": "2025-01-01"}, max_period_days=367
    )


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-01"},
        {"date_to": "2026-10-20"},
        {"period": "custom"},
        {"date_from": "2026-10-21", "date_to": "2026-10-20"},
        {"period": "last_7_days", "date_from": "2026-10-01", "date_to": "2026-10-20"},
        {"date_from": "2026-02-30", "date_to": "2026-03-01"},
        {"date_from": "20.10.2026", "date_to": "2026-10-20"},
        {"date_from": "20261020", "date_to": "2026-10-20"},
        {"date_from": "2026-10-20T00:00:00Z", "date_to": "2026-10-20"},
        {"date_from": "2026-1-1", "date_to": "2026-10-20"},
        {"date_from": "9999-12-30", "date_to": "9999-12-31"},
        {"timezone": "Mars/Olympus"},
        {"timezone": ""},
        {"timezone": "/etc/passwd"},
        {"period": "all_time"},
        {"extra": "value"},
        {"date_from": 20261020, "date_to": "2026-10-20"},
        {"date_from": datetime(2026, 10, 20, tzinfo=UTC), "date_to": "2026-10-20"},
    ],
)
def test_invalid_query_model(params):
    with pytest.raises(ValidationError):
        AnalyticsPeriodParams.model_validate(params)


def test_date_objects_are_supported_in_python():
    result = resolve({"date_from": date(2026, 10, 20), "date_to": date(2026, 10, 20)})
    assert result.date_from == date(2026, 10, 20)


def test_resolved_period_is_immutable():
    result = resolve()
    with pytest.raises(ValidationError):
        result.date_from = date(2026, 1, 1)


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="must include a timezone"):
        resolve(now=NOW.replace(tzinfo=None))


def test_utc_conversion_overflow_is_a_validation_error():
    with pytest.raises(ValueError, match="outside the supported"):
        resolve({"date_from": "0001-01-01", "date_to": "0001-01-01"})


def test_skipped_calendar_day_is_rejected():
    with pytest.raises(ValueError, match="no existing time"):
        resolve(
            {
                "date_from": "2011-12-30",
                "date_to": "2011-12-30",
                "timezone": "Pacific/Apia",
            }
        )


@pytest.mark.parametrize(
    "config",
    [{"timezone": "invalid"}, {"max_period_days": 0}, {"max_period_days": 36601}],
)
def test_invalid_settings(config):
    with pytest.raises(ValidationError):
        settings(**config)


@pytest.fixture
def period_client(monkeypatch):
    monkeypatch.setattr(dependency, "analytics_settings", settings())
    monkeypatch.setattr(
        dependency,
        "resolve_analytics_period",
        lambda params, config: resolve_analytics_period(params, config, now=NOW),
    )
    app = FastAPI()

    @app.get("/period", response_model=ResolvedAnalyticsPeriod)
    def get_period(
        period: Annotated[
            ResolvedAnalyticsPeriod, Depends(dependency.get_analytics_period)
        ],
    ):
        return period

    with TestClient(app) as client:
        yield client


def test_http_dependency_accepts_custom_period(period_client):
    response = period_client.get(
        "/period", params={"date_from": "2026-10-20", "date_to": "2026-10-20"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "period": "custom",
        "date_from": "2026-10-20",
        "date_to": "2026-10-20",
        "timezone": "Asia/Omsk",
        "start_at": "2026-10-19T18:00:00Z",
        "end_at": "2026-10-20T18:00:00Z",
    }


@pytest.mark.parametrize(
    "period", ["current_month", "previous_month", "last_7_days", "last_30_days"]
)
def test_http_dependency_accepts_presets(period_client, period):
    response = period_client.get("/period", params={"period": period})
    assert response.status_code == 200
    assert response.json()["period"] == period


def test_http_dependency_defaults_to_current_month(period_client):
    response = period_client.get("/period")
    assert response.status_code == 200
    assert response.json()["period"] == "current_month"


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-01"},
        {"date_from": "2026-10-21", "date_to": "2026-10-20"},
        {"date_from": "2026-02-30", "date_to": "2026-10-20"},
        {"date_from": "2026-10-20T00:00:00Z", "date_to": "2026-10-20"},
        {"period": "custom"},
        {"period": "invalid"},
        {
            "period": "previous_month",
            "date_from": "2026-10-01",
            "date_to": "2026-10-20",
        },
        {"timezone": "invalid"},
        {"unexpected": "parameter"},
        {"date_from": "2024-01-01", "date_to": "2025-01-01"},
        {"date_from": "0001-01-01", "date_to": "0001-01-01"},
    ],
)
def test_http_dependency_returns_422_for_invalid_period(period_client, params):
    assert period_client.get("/period", params=params).status_code == 422
