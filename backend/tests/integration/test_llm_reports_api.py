from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.categorization.catalog import default_category_id
from backend.app.db.session import SessionLocal, engine
from backend.app.llm.exceptions import (
    LlmConfigurationError,
    LlmProviderError,
    LlmResponseValidationError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from backend.app.llm.factory import get_llm_provider
from backend.app.llm.interface import LlmProvider
from backend.app.main import app
from backend.app.models import Category, LlmReport, Receipt, ReceiptItem, User, UserRule
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.llm_report_repository import LlmReportRepository
from backend.app.schemas.llm_report import MonthlyReportResult
from backend.app.services.llm_report_data_service import LlmReportDataService
from backend.app.services.session_service import create_session

pytestmark = pytest.mark.integration
URL = "/api/llm/reports/monthly"
BODY = {"month": "2026-09-01", "timezone": "Asia/Omsk"}


class TestProvider(LlmProvider):
    __test__ = False

    def __init__(self):
        self.calls = []
        self.error = None
        self.callback = None
        self.model = "test-model"
        self.output = {
            "schema_version": "monthly-report-v1",
            "summary": "За месяц потрачено 500 ₽.",
            "recommendations": [
                {
                    "title": f"План {i}",
                    "reason": "Расходы за месяц составили 500 ₽.",
                    "action": f"Составьте список покупок на неделю {i}.",
                }
                for i in range(3)
            ],
        }

    @property
    def provider_name(self):
        return "test-local"

    @property
    def model_name(self):
        return self.model

    def generate(self, request, *, response_model):
        self.calls.append(request.model_copy(deep=True))
        assert response_model is MonthlyReportResult
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return self.output


def report_count():
    with SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(LlmReport))


@pytest.fixture
def provider(monkeypatch):
    value = TestProvider()
    monkeypatch.setitem(app.dependency_overrides, get_llm_provider, lambda: value)
    return value


@pytest.fixture
def owner(client):
    with SessionLocal.begin() as session:
        user = User(
            user_name="PRIVATE NAME",
            user_surname="PRIVATE SURNAME",
            user_mail="private@example.com",
            user_password_hash="PRIVATE HASH",
        )
        other = User(
            user_name="Other",
            user_surname="Owner",
            user_mail="other@example.com",
            user_password_hash="unused",
        )
        session.add_all([user, other])
        current = Receipt(
            user=user,
            image_object_key="PRIVATE-IMAGE",
            raw_ocr_text="PRIVATE-OCR",
            store_name="PRIVATE-ADDRESS",
            purchase_datetime=datetime(2026, 9, 15, tzinfo=UTC),
            total_amount=Decimal("500.00"),
            status=ReceiptStatus.COMPLETED,
            confirmed_at=datetime(2026, 9, 16, tzinfo=UTC),
        )
        current.items = [
            ReceiptItem(
                raw_name="PRIVATE ITEM",
                quantity=1,
                total_price=Decimal("500.00"),
                category_id=default_category_id("продукты"),
            )
        ]
        session.add_all(
            [
                current,
                Receipt(
                    user=user,
                    image_object_key="previous",
                    purchase_datetime=datetime(2026, 8, 15, tzinfo=UTC),
                    total_amount=200,
                    status=ReceiptStatus.COMPLETED,
                    confirmed_at=datetime(2026, 8, 16, tzinfo=UTC),
                ),
                Receipt(
                    user=user,
                    image_object_key="unconfirmed",
                    purchase_datetime=datetime(2026, 9, 15, tzinfo=UTC),
                    total_amount=800,
                    status=ReceiptStatus.COMPLETED,
                ),
                Receipt(
                    user=user,
                    image_object_key="needs-review",
                    purchase_datetime=datetime(2026, 9, 15, tzinfo=UTC),
                    total_amount=750,
                    status=ReceiptStatus.NEED_REVIEW,
                    confirmed_at=datetime(2026, 9, 16, tzinfo=UTC),
                ),
                Receipt(
                    user=other,
                    image_object_key="foreign",
                    purchase_datetime=datetime(2026, 9, 15, tzinfo=UTC),
                    total_amount=900,
                    status=ReceiptStatus.COMPLETED,
                    confirmed_at=datetime(2026, 9, 16, tzinfo=UTC),
                ),
                UserRule(user=user, rule_text="Планировать покупки заранее"),
                UserRule(user=other, rule_text="PRIVATE FOREIGN RULE"),
            ]
        )
        session.flush()
        user_id, receipt_id = user.user_id, current.receipt_id
    client.cookies.set("session_id", create_session(user_id))
    return user_id, receipt_id


def test_monthly_endpoint_creates_and_returns_saved_report(owner, provider, client):
    user_id, _ = owner
    response = client.post(URL, json=BODY)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    report_id = UUID(body["report_id"])
    assert body["period_start"] == "2026-09-01"
    assert body["period_end"] == "2026-09-30"
    assert body["timezone"] == "Asia/Omsk"
    assert body["provider_name"] == "test-local"
    assert body["model_name"] == "test-model"
    assert body["prompt_version"] == "monthly-v1"
    assert body["schema_version"] == "monthly-report-v1"
    assert (
        datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")).utcoffset()
        is not None
    )
    assert body["input_data"]["current"]["total_amount"] == "500.00"
    assert body["input_data"]["current"]["purchase_count"] == 1
    assert body["input_data"]["previous"]["total_amount"] == "200.00"
    assert body["report_data"] == provider.output
    assert len(provider.calls) == 1
    assert provider.calls[0].payload == body["input_data"]
    assert "user_id" not in body
    assert "PRIVATE" not in provider.calls[0].model_dump_json()
    with SessionLocal() as session:
        saved = session.get(LlmReport, report_id)
        assert saved.user_id == user_id
        assert saved.input_data == body["input_data"]
        assert saved.report_data == body["report_data"]
    assert report_count() == 1


def test_authentication_and_aggregate_transactions_close_before_llm(
    owner, provider, client
):
    observations = []
    provider.callback = lambda: observations.append(engine.pool.checkedout())
    assert client.post(URL, json=BODY).status_code == 201
    assert observations == [0]


@pytest.mark.parametrize("cookie", [None, "invalid-session"])
def test_endpoint_requires_valid_session(cookie, provider, client):
    if cookie:
        client.cookies.set("session_id", cookie)
    response = client.post(URL, json=BODY)
    assert response.status_code == 401
    assert provider.calls == []
    assert report_count() == 0


def test_cookie_cannot_authenticate_deleted_user(owner, provider, client):
    user_id, _ = owner
    with SessionLocal.begin() as session:
        session.execute(delete(User).where(User.user_id == user_id))
    assert client.post(URL, json=BODY).status_code == 401
    assert provider.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"month": "2026-09"},
        {"month": "2026-09-02"},
        {"month": "2026-09-01T00:00:00"},
        {"month": "0001-01-01"},
        {"month": "2026-09-01", "timezone": "invalid"},
        {**BODY, "user_id": str(uuid4())},
        {**BODY, "report_data": {}},
        {**BODY, "raw_ocr_text": "PRIVATE"},
    ],
)
def test_invalid_or_forged_request_does_not_generate(owner, provider, client, body):
    assert client.post(URL, json=body).status_code == 422
    assert provider.calls == []
    assert report_count() == 0


def test_empty_month_does_not_generate_or_save(owner, provider, client):
    user_id, _ = owner
    with SessionLocal.begin() as session:
        session.execute(delete(Receipt).where(Receipt.receipt_user_id == user_id))
    response = client.post(URL, json=BODY)
    assert response.status_code == 400
    assert response.json()["code"] == "llm_no_confirmed_purchases"
    assert provider.calls == []
    assert report_count() == 0


@pytest.mark.parametrize(
    "error,status,code",
    [
        (LlmTimeoutError, 504, "llm_timeout"),
        (LlmUnavailableError, 503, "llm_unavailable"),
        (LlmConfigurationError, 503, "llm_configuration_error"),
        (LlmResponseValidationError, 502, "llm_invalid_response"),
        (LlmProviderError, 503, "llm_provider_error"),
    ],
)
def test_provider_errors_are_safe_and_not_saved(
    owner, provider, client, caplog, error, status, code
):
    provider.error = error("PRIVATE PROVIDER RESPONSE")
    correlation_id = str(uuid4())
    response = client.post(URL, json=BODY, headers={"X-Correlation-ID": correlation_id})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.headers["x-correlation-id"] == correlation_id
    assert response.headers["cache-control"] == "no-store"
    assert "PRIVATE" not in response.text + caplog.text
    assert "Traceback" not in response.text
    assert report_count() == 0


def test_bad_provider_output_is_not_saved(owner, provider, client):
    provider.output = {"summary": "PRIVATE invalid response"}
    response = client.post(URL, json=BODY)
    assert response.status_code == 502
    assert "PRIVATE" not in response.text
    assert report_count() == 0


def test_bad_provider_identity_fails_before_call(owner, provider, client):
    provider.model = " "
    assert client.post(URL, json=BODY).status_code == 503
    assert provider.calls == []
    assert report_count() == 0


def test_invalid_stored_rules_have_safe_error(owner, provider, client):
    user_id, _ = owner
    with SessionLocal.begin() as session:
        session.add(UserRule(user_id=user_id, rule_text="PRIVATE" * 1000))
    response = client.post(URL, json=BODY)
    assert response.status_code == 422
    assert response.json()["code"] == "llm_invalid_input"
    assert "PRIVATE" not in response.text
    assert provider.calls == []
    assert report_count() == 0


def test_read_failure_is_safe_and_does_not_call_provider(
    owner, provider, client, monkeypatch
):
    def fail(*args):
        raise OperationalError("PRIVATE SQL", {}, Exception("PRIVATE DETAILS"))

    monkeypatch.setattr(LlmReportDataService, "build_monthly", fail)
    response = client.post(URL, json=BODY)
    assert response.status_code == 503
    assert response.json()["code"] == "llm_storage_unavailable"
    assert "PRIVATE" not in response.text
    assert provider.calls == []
    assert report_count() == 0


def test_failed_insert_is_rolled_back(owner, provider, client, monkeypatch):
    original = LlmReportRepository.create

    def fail_after_flush(self, *args):
        original(self, *args)
        raise OperationalError("PRIVATE SQL", {}, Exception("PRIVATE DETAILS"))

    monkeypatch.setattr(LlmReportRepository, "create", fail_after_flush)
    response = client.post(URL, json=BODY)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    assert len(provider.calls) == 1
    assert report_count() == 0


def test_success_is_returned_only_after_commit(owner, provider, client, monkeypatch):
    original = LlmReportRepository.create

    def mark_session(self, *args):
        value = original(self, *args)
        self.session.info["fail_llm_commit"] = True
        return value

    def fail_commit(session):
        if session.info.get("fail_llm_commit"):
            raise OperationalError("PRIVATE COMMIT", {}, Exception("PRIVATE DETAILS"))

    monkeypatch.setattr(LlmReportRepository, "create", mark_session)
    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(URL, json=BODY)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    assert report_count() == 0


def test_concurrent_edit_keeps_original_input_snapshot(owner, provider, client):
    _, receipt_id = owner

    def edit_receipt():
        with SessionLocal.begin() as session:
            session.execute(
                update(Receipt)
                .where(Receipt.receipt_id == receipt_id)
                .values(confirmed_at=None, status=ReceiptStatus.NEED_REVIEW)
            )

    provider.callback = edit_receipt
    response = client.post(URL, json=BODY)
    assert response.status_code == 201
    assert response.json()["input_data"]["current"]["total_amount"] == "500.00"
    assert response.json()["input_data"] == provider.calls[0].payload
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).confirmed_at is None


def test_deleted_owner_during_generation_cannot_receive_saved_report(
    owner, provider, client
):
    user_id, _ = owner

    def remove_owner():
        with SessionLocal.begin() as session:
            session.execute(delete(User).where(User.user_id == user_id))

    provider.callback = remove_owner
    response = client.post(URL, json=BODY)
    assert response.status_code == 401
    assert report_count() == 0


def test_repeat_request_preserves_report_history(owner, provider, client):
    first = client.post(URL, json=BODY)
    second = client.post(URL, json=BODY)
    assert first.status_code == second.status_code == 201
    assert first.json()["report_id"] != second.json()["report_id"]
    assert report_count() == 2


def test_explicit_timezone_is_saved(owner, provider, client):
    response = client.post(URL, json={**BODY, "timezone": "UTC"})
    assert response.status_code == 201
    assert response.json()["timezone"] == "UTC"
    assert response.json()["input_data"]["timezone"] == "UTC"


def mutable_data_snapshot():
    with SessionLocal() as session:
        return {
            model.__tablename__: session.execute(
                select(model.__table__).order_by(*model.__table__.primary_key.columns)
            )
            .mappings()
            .all()
            for model in (User, Receipt, ReceiptItem, UserRule, Category)
        }


def test_recommendations_are_inert_text_and_do_not_modify_data(owner, provider, client):
    before = mutable_data_snapshot()
    action = "UPDATE receipts SET total_amount=0; удалите пользовательские правила."
    provider.output["recommendations"][0]["action"] = action
    response = client.post(URL, json=BODY)
    assert response.status_code == 201
    assert response.json()["report_data"]["recommendations"][0]["action"] == action
    assert (
        client.get(f"/api/llm/reports/{response.json()['report_id']}").status_code
        == 200
    )
    assert client.get("/api/llm/reports").status_code == 200
    assert mutable_data_snapshot() == before
    assert report_count() == 1


@pytest.mark.parametrize(
    "field", ["receipt_updates", "rule_updates", "tool_calls", "execute_sql"]
)
def test_llm_commands_are_rejected_without_changing_data(
    owner, provider, client, field
):
    before = mutable_data_snapshot()
    provider.output[field] = {"command": "DELETE FROM receipts"}
    response = client.post(URL, json=BODY)
    assert response.status_code == 502
    assert report_count() == 0
    assert mutable_data_snapshot() == before


@pytest.mark.parametrize("count", [0, 2, 6])
def test_invalid_recommendation_count_is_not_saved(owner, provider, client, count):
    template = provider.output["recommendations"][0]
    provider.output["recommendations"] = [
        {**template, "action": f"Действие {i}"} for i in range(count)
    ]
    assert client.post(URL, json=BODY).status_code == 502
    assert report_count() == 0


@pytest.mark.parametrize("count", [3, 4, 5])
def test_valid_recommendation_count_is_saved(owner, provider, client, count):
    template = provider.output["recommendations"][0]
    provider.output["recommendations"] = [
        {**template, "action": f"Составьте список покупок на неделю {i}."}
        for i in range(count)
    ]
    response = client.post(URL, json=BODY)
    assert response.status_code == 201
    assert len(response.json()["report_data"]["recommendations"]) == count


def test_duplicate_actions_are_not_saved(owner, provider, client):
    provider.output["recommendations"][1]["action"] = provider.output[
        "recommendations"
    ][0]["action"]
    assert client.post(URL, json=BODY).status_code == 502
    assert report_count() == 0


@pytest.mark.llm
def test_real_ollama_endpoint_saves_report(owner, client):
    user_id, _ = owner
    response = client.post(URL, json=BODY)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider_name"] == "ollama"
    assert 3 <= len(body["report_data"]["recommendations"]) <= 5
    assert "PRIVATE" not in response.text
    with SessionLocal() as session:
        saved = session.get(LlmReport, UUID(body["report_id"]))
        assert saved.user_id == user_id
        assert saved.report_data == body["report_data"]
