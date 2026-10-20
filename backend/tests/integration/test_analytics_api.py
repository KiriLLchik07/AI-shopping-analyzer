from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.app.api.dependencies.auth import get_current_user
from backend.app.categorization.catalog import default_category_id
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus

pytestmark = pytest.mark.integration
PATHS = ("summary", "categories", "products/top", "stores", "trends")
PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-31", "timezone": "Asia/Omsk"}


def user():
    return User(
        user_name="Analytics",
        user_surname="Owner",
        user_mail=f"{uuid4()}@example.com",
        user_password_hash="test-hash",
    )


def receipt(
    session,
    owner,
    at,
    amount,
    *,
    store="Магнит",
    status=ReceiptStatus.COMPLETED,
    confirmed=True,
    items=None,
):
    result = Receipt(
        user=owner,
        image_object_key=f"analytics/{uuid4()}.jpg",
        purchase_datetime=at,
        total_amount=Decimal(amount),
        store_name=store,
        status=status,
        confirmed_at=datetime(2026, 11, 10, tzinfo=UTC) if confirmed else None,
    )
    session.add(result)
    for name, normalized, price, category in (
        items if items is not None else [("УТЕЧКА", None, amount, "продукты")]
    ):
        result.items.append(
            ReceiptItem(
                raw_name=name,
                normalized_name=normalized,
                quantity=1,
                unit_price=Decimal(price),
                total_price=Decimal(price),
                category_id=default_category_id(category) if category else None,
                suggested_category_id=default_category_id("продукты"),
            )
        )
    return result


@pytest.fixture
def analytics_data(client, monkeypatch):
    with SessionLocal.begin() as session:
        owner, other = user(), user()
        session.add_all([owner, other])
        first = receipt(
            session,
            owner,
            datetime(2026, 9, 30, 18, tzinfo=UTC),
            "100",
            store="  МАГНИТ ",
            items=[
                ("Молоко", "  МОЛОКО  ", "30", "продукты"),
                ("МОЛОКО", "\tмолоко\n", "20", "продукты"),
                ("ХЛЕБ", None, "50", "продукты"),
            ],
        )
        first.items[0].quantity = Decimal(2)
        first.items[0].unit_price = Decimal("15.00")
        first.items[0].discount_amount = Decimal("10.00")
        first.items[1].quantity = Decimal("0.5")
        first.items[1].unit_price = Decimal("40.00")
        receipt(
            session,
            owner,
            datetime(2026, 10, 4, 12, tzinfo=UTC),
            "200",
            store="\tМагнит  ",
            items=[
                ("Молоко", "молоко", "10", "продукты"),
                ("Шоколад", "шоколад", "190", "сладкое"),
            ],
        )
        receipt(
            session,
            owner,
            datetime(2026, 10, 31, 17, 59, 59, 999999, tzinfo=UTC),
            "50",
            store=None,
            items=[
                ("Неизвестный товар", "   ", "50", None),
            ],
        )
        receipt(
            session, owner, datetime(2026, 9, 30, 17, 59, 59, 999999, tzinfo=UTC), "777"
        )
        receipt(session, owner, datetime(2026, 10, 31, 18, tzinfo=UTC), "999")
        receipt(
            session,
            owner,
            datetime(2026, 10, 5, tzinfo=UTC),
            "400",
            status=ReceiptStatus.NEED_REVIEW,
        )
        receipt(
            session, owner, datetime(2026, 10, 5, tzinfo=UTC), "500", confirmed=False
        )
        receipt(
            session,
            owner,
            datetime(2026, 10, 5, tzinfo=UTC),
            "600",
            status=ReceiptStatus.FAILED,
        )
        receipt(session, owner, None, "10000")
        receipt(session, other, datetime(2026, 10, 5, tzinfo=UTC), "9000")
        session.flush()
        ids = owner.user_id, first.receipt_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    return ids


def get(client, path, **params):
    response = client.get(f"/api/analytics/{path}", params=PERIOD | params)
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_counts_receipts_once_and_excludes_unconfirmed_foreign_and_outside_data(
    analytics_data, client
):
    body = get(client, "summary")
    assert body["total_amount"] == "350.00"
    assert body["purchase_count"] == 3
    assert body["period"]["start_at"] == "2026-09-30T18:00:00Z"
    assert body["period"]["end_at"] == "2026-10-31T18:00:00Z"


def test_categories_use_final_item_amounts_and_actual_not_suggested_category(
    analytics_data, client
):
    body = get(client, "categories")
    rows = {row["category_name"]: row for row in body["items"]}
    assert set(rows) == {"продукты", "сладкое", "Без категории"}
    assert rows["продукты"]["total_amount"] == "110.00"
    assert rows["продукты"]["purchase_count"] == 2
    assert rows["сладкое"]["total_amount"] == "190.00"
    assert rows["сладкое"]["purchase_count"] == 1
    assert rows["Без категории"]["category_id"] is None
    assert rows["Без категории"]["total_amount"] == "50.00"
    assert body["items"][0]["category_name"] == "сладкое"


def test_products_group_normalized_names_and_count_distinct_receipts(
    analytics_data, client
):
    body = get(client, "products/top")
    assert body["sort_by"] == "amount"
    assert body["items"][0] == {
        "product_name": "шоколад",
        "total_amount": "190.00",
        "purchase_count": 1,
    }
    rows = {row["product_name"]: row for row in body["items"]}
    assert len(rows) == 4
    assert rows["молоко"] == {
        "product_name": "молоко",
        "total_amount": "60.00",
        "purchase_count": 2,
    }
    assert rows["хлеб"]["total_amount"] == "50.00"
    assert rows["неизвестный товар"]["total_amount"] == "50.00"


def test_top_products_support_frequency_sort_and_sql_limit(analytics_data, client):
    body = get(client, "products/top", sort_by="frequency", limit=1)
    assert body["limit"] == 1
    assert body["sort_by"] == "frequency"
    assert len(body["items"]) == 1
    assert body["items"][0]["product_name"] == "молоко"
    assert body["items"][0]["purchase_count"] == 2


def test_store_top_uses_receipt_totals_without_item_join(analytics_data, client):
    body = get(client, "stores")
    assert body["items"] == [
        {"store_name": "магнит", "total_amount": "300.00", "purchase_count": 2},
        {"store_name": None, "total_amount": "50.00", "purchase_count": 1},
    ]
    assert get(client, "stores", limit=1)["items"] == body["items"][:1]


def test_daily_trends_fill_missing_days_and_use_local_dates(analytics_data, client):
    body = get(client, "trends")
    assert body["group_by"] == "day"
    assert len(body["points"]) == 31
    rows = {row["bucket_start"]: row for row in body["points"]}
    assert rows["2026-10-01"]["total_amount"] == "100.00"
    assert rows["2026-10-04"]["total_amount"] == "200.00"
    assert rows["2026-10-31"]["total_amount"] == "50.00"
    assert rows["2026-10-02"]["total_amount"] == "0.00"
    assert rows["2026-10-02"]["purchase_count"] == 0
    assert sum(row["purchase_count"] for row in body["points"]) == 3


def test_weekly_trends_start_on_monday_and_keep_partial_first_bucket(
    analytics_data, client
):
    body = get(client, "trends", group_by="week")
    assert len(body["points"]) == 5
    assert body["points"][0] == {
        "bucket_start": "2026-09-28",
        "total_amount": "300.00",
        "purchase_count": 2,
    }
    assert body["points"][-1]["bucket_start"] == "2026-10-26"
    assert body["points"][-1]["total_amount"] == "50.00"
    partial = get(
        client, "trends", group_by="week", date_from="2026-10-02", date_to="2026-10-04"
    )
    assert partial["points"] == [
        {"bucket_start": "2026-09-28", "total_amount": "200.00", "purchase_count": 1}
    ]


def test_monthly_trends_cross_calendar_boundaries(analytics_data, client):
    body = get(
        client, "trends", group_by="month", date_from="2026-09-30", date_to="2026-11-01"
    )
    assert body["points"] == [
        {"bucket_start": "2026-09-01", "total_amount": "777.00", "purchase_count": 1},
        {"bucket_start": "2026-10-01", "total_amount": "350.00", "purchase_count": 3},
        {"bucket_start": "2026-11-01", "total_amount": "999.00", "purchase_count": 1},
    ]


@pytest.mark.parametrize("path", PATHS)
def test_empty_period_returns_zero_totals_or_empty_groups(analytics_data, client, path):
    body = get(client, path, date_from="2026-08-01", date_to="2026-08-02")
    if path == "summary":
        assert body["total_amount"] == "0.00"
        assert body["purchase_count"] == 0
    elif path == "trends":
        assert len(body["points"]) == 2
        assert all(
            row["total_amount"] == "0.00" and row["purchase_count"] == 0
            for row in body["points"]
        )
    else:
        assert body["items"] == []


@pytest.mark.parametrize("path", PATHS)
def test_every_endpoint_requires_authentication(client, path):
    assert client.get(f"/api/analytics/{path}", params=PERIOD).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_every_endpoint_validates_period(analytics_data, client, path):
    response = client.get(
        f"/api/analytics/{path}", params=PERIOD | {"date_to": "2026-09-01"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("products/top", {"limit": 0}),
        ("products/top", {"limit": 101}),
        ("products/top", {"sort_by": "invalid"}),
        ("stores", {"limit": -1}),
        ("stores", {"limit": 101}),
        ("trends", {"group_by": "year"}),
        ("summary", {"user_id": str(uuid4())}),
        ("categories", {"status": "need_review"}),
    ],
)
def test_invalid_or_forged_query_parameters_are_rejected(
    analytics_data, client, path, params
):
    assert (
        client.get(f"/api/analytics/{path}", params=PERIOD | params).status_code == 422
    )


@pytest.mark.parametrize("path", PATHS)
def test_analytics_executes_one_aggregate_query(analytics_data, client, path):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        get(client, path)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "SUM(" in statements[0].upper()
    assert "COUNT(" in statements[0].upper()


def test_selected_timezone_changes_day_membership(analytics_data, client):
    day = {"date_from": "2026-10-01", "date_to": "2026-10-01"}
    assert get(client, "summary", **day)["total_amount"] == "100.00"
    assert (
        get(client, "summary", **(day | {"timezone": "UTC"}))["total_amount"] == "0.00"
    )


def test_edited_receipt_disappears_until_confirmed_again(analytics_data, client):
    _, receipt_id = analytics_data
    assert (
        client.patch(
            f"/api/receipts/{receipt_id}", json={"store_name": "Правка"}
        ).status_code
        == 200
    )
    assert get(client, "summary")["total_amount"] == "250.00"
    assert client.post(f"/api/receipts/{receipt_id}/confirm").status_code == 200
    assert get(client, "summary")["total_amount"] == "350.00"


def test_dst_transition_does_not_shift_or_duplicate_daily_bucket(
    analytics_data, client
):
    owner_id, _ = analytics_data
    with SessionLocal.begin() as session:
        owner = session.get(User, owner_id)
        receipt(session, owner, datetime(2026, 3, 8, 5, tzinfo=UTC), "1")
        receipt(session, owner, datetime(2026, 3, 9, 3, 59, 59, tzinfo=UTC), "2")
        receipt(session, owner, datetime(2026, 3, 9, 4, tzinfo=UTC), "99")
    body = get(
        client,
        "trends",
        date_from="2026-03-08",
        date_to="2026-03-08",
        timezone="America/New_York",
    )
    assert body["points"] == [
        {"bucket_start": "2026-03-08", "total_amount": "3.00", "purchase_count": 2}
    ]
