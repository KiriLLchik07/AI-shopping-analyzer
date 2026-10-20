from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, event

from backend.app.api.dependencies import analytics as dependency
from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.config import AnalyticsSettings
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.services.analytics_period_service import (
    resolve_month_comparison_periods,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
CURRENT_START = datetime(2026, 9, 30, 18, tzinfo=UTC)
URL = "/api/analytics/month-comparison"


def new_user():
    return User(
        user_name="Comparison",
        user_surname="Owner",
        user_mail=f"{uuid4()}@example.com",
        user_password_hash="test-hash",
    )


def add_receipt(
    session, owner, at, amount, *, status=ReceiptStatus.COMPLETED, confirmed=True
):
    result = Receipt(
        user=owner,
        image_object_key=f"comparison/{uuid4()}.jpg",
        purchase_datetime=at,
        total_amount=Decimal(amount),
        status=status,
        confirmed_at=NOW if confirmed else None,
    )
    result.items = [
        ReceiptItem(raw_name="Позиция", quantity=1, total_price=Decimal(amount) / 2)
        for _ in range(2)
    ]
    session.add(result)
    return result


@pytest.fixture
def comparison_data(client, monkeypatch):
    monkeypatch.setattr(
        dependency,
        "analytics_settings",
        AnalyticsSettings(_env_file=None, timezone="Asia/Omsk", max_period_days=366),
    )
    monkeypatch.setattr(
        dependency,
        "resolve_month_comparison_periods",
        lambda params, settings: resolve_month_comparison_periods(
            params, settings, now=NOW
        ),
    )
    with SessionLocal.begin() as session:
        owner, other = new_user(), new_user()
        session.add_all([owner, other])
        add_receipt(session, owner, CURRENT_START, "100")
        add_receipt(
            session, owner, datetime(2026, 10, 20, 11, 59, 59, 999999, tzinfo=UTC), "50"
        )
        add_receipt(session, owner, datetime(2026, 8, 31, 18, tzinfo=UTC), "50")
        add_receipt(
            session, owner, datetime(2026, 9, 20, 11, 59, 59, 999999, tzinfo=UTC), "25"
        )
        add_receipt(session, owner, NOW, "1000")
        add_receipt(session, owner, datetime(2026, 10, 21, tzinfo=UTC), "2000")
        add_receipt(session, owner, datetime(2026, 9, 20, 12, tzinfo=UTC), "3000")
        add_receipt(
            session,
            owner,
            datetime(2026, 8, 31, 17, 59, 59, 999999, tzinfo=UTC),
            "4000",
        )
        add_receipt(session, other, datetime(2026, 10, 8, tzinfo=UTC), "5000")
        for month in (9, 10):
            add_receipt(
                session,
                owner,
                datetime(2026, month, 8, tzinfo=UTC),
                "6000",
                confirmed=False,
            )
            add_receipt(
                session,
                owner,
                datetime(2026, month, 8, tzinfo=UTC),
                "7000",
                status=ReceiptStatus.NEED_REVIEW,
            )
            add_receipt(
                session,
                owner,
                datetime(2026, month, 8, tzinfo=UTC),
                "8000",
                status=ReceiptStatus.FAILED,
            )
        add_receipt(session, owner, None, "9000")
        session.flush()
        owner_id = owner.user_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    return owner_id


def body(client, **params):
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_months_are_compared_in_one_query_without_loading_receipts(
    comparison_data, client
):
    queries = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = body(client)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 1
    assert "FILTER (WHERE" in queries[0]
    assert result["current"] == {
        "start_at": "2026-09-30T18:00:00Z",
        "end_at": "2026-10-20T12:00:00Z",
        "total_amount": "150.00",
        "purchase_count": 2,
    }
    assert result["previous"] == {
        "start_at": "2026-08-31T18:00:00Z",
        "end_at": "2026-09-20T12:00:00Z",
        "total_amount": "75.00",
        "purchase_count": 2,
    }
    assert result["comparison_basis"] == "month_to_date"
    assert result["timezone"] == "Asia/Omsk"
    assert result["as_of"] == "2026-10-20T12:00:00Z"
    assert result["amount_change"] == "75.00"
    assert result["amount_change_percent"] == "100.00"
    assert result["purchase_count_change"] == 0
    assert result["purchase_count_change_percent"] == "0.00"


def test_growth_and_count_percentages(comparison_data, client):
    with SessionLocal.begin() as session:
        add_receipt(
            session,
            session.get(User, comparison_data),
            datetime(2026, 10, 9, tzinfo=UTC),
            "25",
        )
    result = body(client)
    assert result["amount_change"] == "100.00"
    assert result["amount_change_percent"] == "133.33"
    assert result["purchase_count_change"] == 1
    assert result["purchase_count_change_percent"] == "50.00"


@pytest.mark.parametrize("remove", ["previous", "current", "both"])
def test_empty_months_and_zero_baseline(comparison_data, client, remove):
    with SessionLocal.begin() as session:
        query = delete(Receipt).where(Receipt.receipt_user_id == comparison_data)
        if remove == "previous":
            query = query.where(Receipt.purchase_datetime < CURRENT_START)
        elif remove == "current":
            query = query.where(Receipt.purchase_datetime >= CURRENT_START)
        session.execute(query)
    result = body(client)
    if remove == "previous":
        assert result["amount_change"] == "150.00"
        assert result["amount_change_percent"] is None
        assert result["purchase_count_change_percent"] is None
    elif remove == "current":
        assert result["amount_change"] == "-75.00"
        assert result["amount_change_percent"] == "-100.00"
        assert result["purchase_count_change"] == -2
    else:
        assert (
            result["current"]["purchase_count"]
            == result["previous"]["purchase_count"]
            == 0
        )
        assert (
            result["amount_change_percent"]
            == result["purchase_count_change_percent"]
            == "0.00"
        )


def test_current_month_is_selected_in_requested_timezone(comparison_data, client):
    result = body(client, timezone="UTC")
    assert result["current"]["start_at"] == "2026-10-01T00:00:00Z"
    assert result["previous"]["start_at"] == "2026-09-01T00:00:00Z"
    assert result["current"]["total_amount"] == "50.00"
    assert result["previous"]["total_amount"] == "25.00"


@pytest.mark.parametrize(
    "params",
    [
        {"timezone": "invalid"},
        {"period": "previous_month"},
        {"date_from": "2026-01-01"},
        {"user_id": str(uuid4())},
    ],
)
def test_invalid_or_forged_query_parameters_are_rejected(
    comparison_data, client, params
):
    assert client.get(URL, params=params).status_code == 422


def test_comparison_requires_authentication(client):
    assert client.get(URL).status_code == 401
