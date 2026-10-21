import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from backend.app.db.session import SessionLocal, engine
from backend.app.llm.factory import get_llm_provider
from backend.app.main import app
from backend.app.models import LlmReport, User
from backend.app.repositories.llm_report_repository import LlmReportRepository
from backend.app.services.session_service import create_session

pytestmark = pytest.mark.integration
URL = "/api/llm/reports"
STAMP = datetime(2026, 10, 21, 12, tzinfo=UTC)


def saved_report(user_id, report_id, at=STAMP):
    data = json.loads(
        (
            Path(__file__).resolve().parents[1] / "llm" / "fixtures" / "monthly.json"
        ).read_text(encoding="utf-8")
    )
    return LlmReport(
        report_id=report_id,
        user_id=user_id,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        timezone="Asia/Omsk",
        input_data=data,
        report_data={
            "schema_version": "monthly-report-v1",
            "summary": "Сохранённый отчёт",
            "recommendations": [
                {
                    "title": f"План {i}",
                    "reason": "Данные за месяц",
                    "action": f"Составьте план на неделю {i}.",
                }
                for i in range(3)
            ],
        },
        prompt_version="monthly-v1",
        schema_version="monthly-report-v1",
        provider_name="saved-local",
        model_name="saved-model",
        created_at=at,
    )


@pytest.fixture
def saved_data(client, monkeypatch):
    with SessionLocal.begin() as session:
        users = [
            User(
                user_name="Test",
                user_surname="Owner",
                user_mail=f"{uuid4()}@example.com",
                user_password_hash="unused",
            )
            for _ in range(3)
        ]
        session.add_all(users)
        session.flush()
        first, foreign, empty = [u.user_id for u in users]
        session.add_all(
            [
                saved_report(first, UUID(int=16)),
                saved_report(first, UUID(int=32)),
                saved_report(first, UUID(int=48), datetime(2026, 10, 20, tzinfo=UTC)),
                saved_report(foreign, UUID(int=64)),
            ]
        )

    def forbid_provider():
        pytest.fail("Reading reports must not initialize an LLM provider")

    monkeypatch.setitem(app.dependency_overrides, get_llm_provider, forbid_provider)
    client.cookies.set("session_id", create_session(first))
    return first, foreign, empty


def test_list_is_owner_scoped_paginated_and_lightweight(saved_data, client):
    response = client.get(URL, params={"page_size": 2})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    assert (
        value["page"],
        value["page_size"],
        value["total"],
        value["total_pages"],
    ) == (1, 2, 3, 2)
    assert [i["report_id"] for i in value["items"]] == [
        str(UUID(int=32)),
        str(UUID(int=16)),
    ]
    for item in value["items"]:
        assert item["model_name"] == "saved-model"
        assert "input_data" not in item
        assert "report_data" not in item
        assert "user_id" not in item
    second = client.get(URL, params={"page": 2, "page_size": 2}).json()
    assert [i["report_id"] for i in second["items"]] == [str(UUID(int=48))]
    assert second["total"] == 3


def test_detail_returns_persisted_snapshot_without_regenerating(saved_data, client):
    report_id = UUID(int=32)
    with SessionLocal() as session:
        value = session.get(LlmReport, report_id)
        input_data, report_data = value.input_data, value.report_data
    response = client.get(f"{URL}/{report_id}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["input_data"] == {
        "schema_version": "monthly-input-v1",
        "currency": "RUB",
        **input_data,
    }
    assert response.json()["report_data"] == report_data
    assert response.json()["model_name"] == "saved-model"
    assert response.json()["prompt_version"] == "monthly-v1"


def test_foreign_and_missing_reports_are_indistinguishable(saved_data, client):
    foreign = client.get(f"{URL}/{UUID(int=64)}")
    missing = client.get(f"{URL}/{uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_other_user_can_only_read_own_reports(saved_data, client):
    _, foreign, _ = saved_data
    client.cookies.set("session_id", create_session(foreign))
    assert [i["report_id"] for i in client.get(URL).json()["items"]] == [
        str(UUID(int=64))
    ]
    assert client.get(f"{URL}/{UUID(int=32)}").status_code == 404
    assert client.get(f"{URL}/{UUID(int=64)}").status_code == 200


@pytest.mark.parametrize("path", [URL, f"{URL}/{UUID(int=32)}"])
def test_saved_reports_require_authentication(path, client):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page": 1000001},
        {"page_size": 0},
        {"page_size": 101},
        {"page": "wrong"},
        {"user_id": str(uuid4())},
    ],
)
def test_pagination_and_extra_query_params_are_validated(saved_data, client, params):
    assert client.get(URL, params=params).status_code == 422


def test_invalid_report_uuid_is_rejected(saved_data, client):
    assert client.get(f"{URL}/not-a-uuid").status_code == 422


def test_empty_list_and_page_beyond_end(saved_data, client):
    beyond = client.get(URL, params={"page": 99}).json()
    assert beyond["items"] == [] and beyond["total"] == 3
    client.cookies.set("session_id", create_session(saved_data[2]))
    empty = client.get(URL).json()
    assert empty["items"] == [] and empty["total"] == empty["total_pages"] == 0


def test_list_sql_does_not_fetch_full_report_json(saved_data, client):
    statements = []

    def capture(_conn, _cursor, statement, _params, _ctx, _many):
        if "llm_reports" in statement.lower():
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(URL, params={"page_size": 1})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(statements) == 2
    assert all("input_data" not in q and "report_data" not in q for q in statements)
    assert any("limit" in q and "offset" in q for q in statements)


def test_count_and_items_share_the_same_snapshot(saved_data, client, monkeypatch):
    original = LlmReportRepository.count_for_user
    inserted = False

    def count_and_insert(self, user_id):
        nonlocal inserted
        count = original(self, user_id)
        if not inserted:
            inserted = True
            with SessionLocal.begin() as session:
                session.add(saved_report(user_id, UUID(int=80)))
        return count

    monkeypatch.setattr(LlmReportRepository, "count_for_user", count_and_insert)
    first = client.get(URL).json()
    assert first["total"] == len(first["items"]) == 3
    second = client.get(URL).json()
    assert second["total"] == len(second["items"]) == 4


@pytest.mark.parametrize(
    "method,path", [("count_for_user", URL), ("get_for_user", f"{URL}/{UUID(int=32)}")]
)
def test_read_errors_are_safe(saved_data, client, monkeypatch, method, path):
    def fail(*args):
        raise OperationalError("PRIVATE SQL", {}, Exception("PRIVATE DETAILS"))

    monkeypatch.setattr(LlmReportRepository, method, fail)
    response = client.get(path)
    assert response.status_code == 503
    assert response.json()["code"] == "llm_storage_unavailable"
    assert "PRIVATE" not in response.text


def test_legacy_duplicate_recommendations_remain_readable(saved_data, client):
    with SessionLocal.begin() as session:
        report = session.get(LlmReport, UUID(int=32))
        value = dict(report.report_data)
        value["recommendations"] = [value["recommendations"][0]] * 3
        report.report_data = value
    assert client.get(f"{URL}/{UUID(int=32)}").status_code == 200


def test_invalid_stored_json_returns_safe_error_without_regeneration(
    saved_data, client
):
    with SessionLocal.begin() as session:
        report = session.get(LlmReport, UUID(int=32))
        report.report_data = {"summary": "PRIVATE INVALID RECORD"}
    response = client.get(f"{URL}/{UUID(int=32)}")
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    assert response.json()["code"] == "llm_storage_unavailable"
    assert client.get(URL).status_code == 200
