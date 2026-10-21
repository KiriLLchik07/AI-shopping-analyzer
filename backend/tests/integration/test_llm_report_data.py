import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text, update
from sqlalchemy.exc import InternalError

from backend.app.categorization.catalog import default_category_id
from backend.app.core.config import AnalyticsSettings
from backend.app.db.session import SessionLocal, engine
from backend.app.llm.prompts.monthly_v1 import build_monthly_request
from backend.app.models import Receipt, ReceiptItem, User, UserRule
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.analytics_repository import AnalyticsRepository
from backend.app.repositories.llm_report_data_repository import LlmReportDataRepository
from backend.app.schemas.llm_report import MonthlyReportParams
from backend.app.services.llm_report_data_service import LlmReportDataService

pytestmark = pytest.mark.integration
MONTH = MonthlyReportParams(month=date(2026, 10, 1))
CONFIRMED_AT = datetime(2026, 10, 20, 12, tzinfo=UTC)


def service():
    return LlmReportDataService(SessionLocal, AnalyticsSettings(_env_file=None))


def user(email):
    return User(
        user_name="PRIVATE FIRST",
        user_surname="PRIVATE LAST",
        user_mail=email,
        user_password_hash="PRIVATE HASH",
    )


def receipt(owner, at, amount, *, status=ReceiptStatus.COMPLETED, confirmed=True):
    return Receipt(
        user=owner,
        purchase_datetime=at,
        total_amount=Decimal(amount),
        status=status,
        confirmed_at=CONFIRMED_AT if confirmed else None,
        image_object_key="PRIVATE-IMAGE-KEY",
        raw_ocr_text="PRIVATE-OCR-TEXT",
        store_name="PRIVATE-STORE-ADDRESS",
        fiscal_drive_number="PRIVATE-FN",
    )


@pytest.fixture
def monthly_data(db_session):
    owner, foreign = (
        user("private-owner@example.com"),
        user("foreign-owner@example.com"),
    )
    first = receipt(owner, datetime(2026, 9, 30, 18, tzinfo=UTC), "100.00")
    second = receipt(owner, datetime(2026, 10, 10, 12, tzinfo=UTC), "250.00")
    last = receipt(
        owner, datetime(2026, 10, 31, 17, 59, 59, 999999, tzinfo=UTC), "50.00"
    )
    previous = receipt(owner, datetime(2026, 8, 31, 18, tzinfo=UTC), "200.00")
    products, sweets = default_category_id("продукты"), default_category_id("сладкое")
    for value, category, amount in [
        (first, products, "100"),
        (second, products, "200"),
        (second, sweets, "50"),
        (last, None, "50"),
        (previous, products, "200"),
    ]:
        db_session.add(
            ReceiptItem(
                receipt=value,
                raw_name="PRIVATE RAW ITEM NAME",
                normalized_name="PRIVATE NORMALIZED NAME",
                category_id=category,
                quantity=1,
                total_price=Decimal(amount),
            )
        )
    db_session.add_all(
        [
            receipt(owner, datetime(2026, 8, 31, 17, 59, tzinfo=UTC), "888"),
            receipt(owner, datetime(2026, 10, 31, 18, tzinfo=UTC), "999"),
            receipt(owner, datetime(2026, 10, 5, tzinfo=UTC), "999", confirmed=False),
            receipt(owner, None, "999"),
            receipt(foreign, datetime(2026, 10, 5, tzinfo=UTC), "3333"),
            UserRule(user=owner, rule_text="Расходы на кафе — до 5 000 ₽ в месяц"),
            UserRule(user=owner, rule_text="PRIVATE-DISABLED-RULE", is_active=False),
            UserRule(user=foreign, rule_text="PRIVATE-FOREIGN-RULE"),
            *[
                receipt(owner, datetime(2026, 10, 5, tzinfo=UTC), "999", status=status)
                for status in ReceiptStatus
                if status != ReceiptStatus.COMPLETED
            ],
        ]
    )
    db_session.commit()
    return owner.user_id, first.receipt_id


def test_monthly_input_matches_confirmed_owner_aggregates(monthly_data):
    owner_id, _ = monthly_data
    value = service().build_monthly(owner_id, MONTH)
    assert value.timezone == "Asia/Omsk"
    assert value.current.date_from == date(2026, 10, 1)
    assert value.current.date_to == date(2026, 10, 31)
    assert value.current.total_amount == Decimal("400.00")
    assert value.current.purchase_count == 3
    assert value.previous.date_from == date(2026, 9, 1)
    assert value.previous.date_to == date(2026, 9, 30)
    assert value.previous.total_amount == Decimal("200.00")
    assert value.previous.purchase_count == 1
    assert [
        (c.category_name, c.total_amount, c.purchase_count) for c in value.categories
    ] == [
        ("продукты", Decimal("300.00"), 2),
        ("Без категории", Decimal("50.00"), 1),
        ("сладкое", Decimal("50.00"), 1),
    ]
    assert len(value.weekly_trends) == 5
    assert value.weekly_trends[0].bucket_start == date(2026, 9, 28)
    assert [p.total_amount for p in value.weekly_trends] == [
        Decimal(100),
        Decimal(250),
        Decimal(0),
        Decimal(0),
        Decimal(50),
    ]
    assert sum(p.purchase_count for p in value.weekly_trends) == 3
    assert value.rules == ("Расходы на кафе — до 5 000 ₽ в месяц",)


def test_provider_request_excludes_all_receipt_and_identity_secrets(monthly_data):
    owner_id, first_id = monthly_data
    request = build_monthly_request(service().build_monthly(owner_id, MONTH))
    serialized = request.model_dump_json()
    assert "PRIVATE" not in serialized
    assert "@example.com" not in serialized
    assert str(owner_id) not in serialized
    assert str(first_id) not in serialized
    for field in (
        "raw_ocr_text",
        "image_object_key",
        "fiscal_drive_number",
        "raw_name",
        "normalized_name",
        "store_name",
        "user_id",
        "category_id",
        "rule_id",
    ):
        assert field not in request.payload
        assert field not in json.dumps(request.payload)


def test_data_is_deterministic_and_does_not_change_database(monthly_data):
    owner_id, _ = monthly_data
    first = service().build_monthly(owner_id, MONTH)
    second = service().build_monthly(owner_id, MONTH)
    assert first.model_dump_json() == second.model_dump_json()
    assert build_monthly_request(first) == build_monthly_request(second)


def test_only_projected_aggregates_are_read_with_sql(monthly_data):
    owner_id, _ = monthly_data
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record)
    try:
        service().build_monthly(owner_id, MONTH)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    selects = [q for q in statements if q.lstrip().startswith("select")]
    assert len(selects) == 5
    assert sum("sum(" in q and "count(" in q for q in selects) == 4
    assert all(q.lstrip().startswith("select") for q in statements)
    for forbidden in (
        "raw_ocr_text",
        "image_object_key",
        "raw_name",
        "normalized_name",
        "user_password_hash",
        "user_mail",
        "fiscal_drive_number",
    ):
        assert all(forbidden not in q for q in statements)


def test_transaction_is_read_only_and_repeatable_read(monthly_data, monkeypatch):
    owner_id, _ = monthly_data
    original = LlmReportDataRepository.monthly_aggregates
    observed = {}

    def inspect_transaction(self, *args):
        observed["isolation"] = self.session.scalar(text("SHOW transaction_isolation"))
        observed["readonly"] = self.session.scalar(text("SHOW transaction_read_only"))
        return original(self, *args)

    monkeypatch.setattr(
        LlmReportDataRepository, "monthly_aggregates", inspect_transaction
    )
    service().build_monthly(owner_id, MONTH)
    assert observed == {"isolation": "repeatable read", "readonly": "on"}


def test_read_only_transaction_rejects_accidental_writes(monthly_data, monkeypatch):
    owner_id, receipt_id = monthly_data

    def write_instead_of_collecting(self, *args):
        self.session.execute(
            update(Receipt)
            .where(Receipt.receipt_id == receipt_id)
            .values(total_amount=999)
        )

    monkeypatch.setattr(
        LlmReportDataRepository, "monthly_aggregates", write_instead_of_collecting
    )
    with pytest.raises(InternalError, match="read-only"):
        service().build_monthly(owner_id, MONTH)


def test_concurrent_edit_does_not_mix_two_snapshots(monthly_data, monkeypatch):
    owner_id, receipt_id = monthly_data
    original = AnalyticsRepository.summary
    changed = False

    def edit_after_summary(self, user_id, period):
        nonlocal changed
        result = original(self, user_id, period)
        if not changed and period.date_from == date(2026, 10, 1):
            changed = True
            with SessionLocal.begin() as writer:
                writer.execute(
                    update(Receipt)
                    .where(Receipt.receipt_id == receipt_id)
                    .values(confirmed_at=None)
                )
        return result

    monkeypatch.setattr(AnalyticsRepository, "summary", edit_after_summary)
    first = service().build_monthly(owner_id, MONTH)
    assert changed
    assert (
        first.current.total_amount
        == sum(w.total_amount for w in first.weekly_trends)
        == sum(c.total_amount for c in first.categories)
        == Decimal("400.00")
    )
    assert first.current.purchase_count == 3
    second = service().build_monthly(owner_id, MONTH)
    assert second.current.total_amount == Decimal("300.00")
    assert second.current.purchase_count == 2


def test_empty_month_produces_zero_aggregates():
    value = service().build_monthly(uuid4(), MONTH)
    assert value.current.total_amount == value.previous.total_amount == Decimal("0.00")
    assert value.current.purchase_count == value.previous.purchase_count == 0
    assert value.categories == value.rules == ()
    assert len(value.weekly_trends) == 5
    assert all(
        w.total_amount == 0 and w.purchase_count == 0 for w in value.weekly_trends
    )


@pytest.mark.parametrize(
    "month,zone,previous_from,last",
    [
        (date(2026, 1, 1), "Asia/Omsk", date(2025, 12, 1), 31),
        (date(2024, 2, 1), "Asia/Omsk", date(2024, 1, 1), 29),
        (date(2026, 3, 1), "America/New_York", date(2026, 2, 1), 31),
    ],
)
def test_calendar_year_leap_and_dst_periods(month, zone, previous_from, last):
    value = service().build_monthly(
        uuid4(), MonthlyReportParams(month=month, timezone=zone)
    )
    assert value.current.date_from == month
    assert value.current.date_to == month.replace(day=last)
    assert value.previous.date_from == previous_from
    assert value.timezone == zone


def test_timezone_changes_month_membership(monthly_data):
    owner_id, _ = monthly_data
    value = service().build_monthly(
        owner_id, MonthlyReportParams(month=date(2026, 10, 1), timezone="UTC")
    )
    assert value.current.purchase_count == 3
    assert value.current.total_amount == Decimal("1299.00")
    assert value.previous.total_amount == Decimal("100.00")


def test_rule_limit_fails_instead_of_silently_dropping_rules(monthly_data):
    owner_id, _ = monthly_data
    with SessionLocal.begin() as session:
        session.add_all(
            [UserRule(user_id=owner_id, rule_text=f"Правило {i}") for i in range(20)]
        )
    with pytest.raises(ValidationError, match="rules"):
        service().build_monthly(owner_id, MONTH)
