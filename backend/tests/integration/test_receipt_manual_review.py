from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, User
from backend.app.models.enums import ReceiptStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def review_receipt(client, monkeypatch):
    with SessionLocal.begin() as session:
        user = User(
            user_name="Review",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(
            user=user,
            image_object_key="review/test.jpg",
            store_name="Старый магазин",
            purchase_datetime=datetime(2026, 10, 19, 6, tzinfo=UTC),
            total_amount=Decimal("100.00"),
            status=ReceiptStatus.NEED_REVIEW,
            raw_ocr_text="Исходный текст",
        )
        session.add(receipt)
        session.flush()
        receipt_id = receipt.receipt_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    return receipt_id


def test_edit_receipt_metadata_persists_and_is_available_for_review(
    review_receipt, client
):
    url = f"/api/receipts/{review_receipt}"
    response = client.patch(
        url,
        json={
            "store_name": "  Исправленный магазин  ",
            "purchase_datetime": "2026-10-20T17:46:12+06:00",
            "total_amount": "3240.15",
        },
    )
    assert response.status_code == 200
    for body in (response.json(), client.get(url).json()):
        assert body["store_name"] == "Исправленный магазин"
        assert datetime.fromisoformat(body["purchase_datetime"]) == datetime(
            2026, 10, 20, 11, 46, 12, tzinfo=UTC
        )
        assert body["total_amount"] == "3240.15"
        assert body["status"] == "need_review"
        assert body["raw_ocr_text"] == "Исходный текст"
    with SessionLocal() as session:
        receipt = session.get(Receipt, review_receipt)
        assert receipt.total_amount == Decimal("3240.15")
        assert receipt.purchase_datetime == datetime(
            2026, 10, 20, 11, 46, 12, tzinfo=UTC
        )
        assert receipt.manually_updated_fields == [
            "purchase_datetime",
            "store_name",
            "total_amount",
        ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store_name", "Другой магазин"),
        ("purchase_datetime", "2026-10-21T01:00:00Z"),
        ("total_amount", "9999999999.99"),
        ("total_amount", "0.01"),
        ("store_name", None),
        ("purchase_datetime", None),
        ("total_amount", None),
    ],
)
def test_patch_changes_only_explicit_field(review_receipt, client, field, value):
    url = f"/api/receipts/{review_receipt}"
    before = client.get(url).json()
    response = client.patch(url, json={field: value})
    assert response.status_code == 200
    after = client.get(url).json()
    if field == "purchase_datetime" and value is not None:
        assert datetime.fromisoformat(after[field]) == datetime.fromisoformat(value)
    else:
        assert after[field] == value
    for omitted in {"store_name", "purchase_datetime", "total_amount"} - {field}:
        assert after[omitted] == before[omitted]
    with SessionLocal() as session:
        assert session.get(Receipt, review_receipt).manually_updated_fields == [field]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"store_name": ""},
        {"store_name": " \t\n "},
        {"store_name": "а" * 101},
        {"purchase_datetime": "2026-10-20T17:46:00"},
        {"purchase_datetime": "2026-10-20"},
        {"purchase_datetime": "2026-02-30T17:46:00+06:00"},
        {"total_amount": "-0.01"},
        {"total_amount": "0"},
        {"total_amount": "123.456"},
        {"total_amount": "10000000000.00"},
        {"total_amount": "NaN"},
        {"total_amount": "Infinity"},
        {"status": "completed"},
        {"manually_updated_fields": []},
        {"store_name": "Не сохранять", "total_amount": "-1"},
    ],
)
def test_invalid_edit_is_rejected_without_partial_save(review_receipt, client, payload):
    url = f"/api/receipts/{review_receipt}"
    before = client.get(url).json()
    assert client.patch(url, json=payload).status_code == 422
    assert client.get(url).json() == before
    with SessionLocal() as session:
        assert session.get(Receipt, review_receipt).manually_updated_fields == []


def test_receipt_edit_requires_owner(review_receipt, client, monkeypatch):
    with SessionLocal.begin() as session:
        other = User(
            user_name="Other",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        session.add(other)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: other)
    response = client.patch(
        f"/api/receipts/{review_receipt}", json={"store_name": "Чужая правка"}
    )
    assert response.status_code == 404
    with SessionLocal() as session:
        receipt = session.get(Receipt, review_receipt)
        assert receipt.store_name == "Старый магазин"
        assert receipt.manually_updated_fields == []


def test_receipt_edit_requires_authentication(client):
    response = client.patch(f"/api/receipts/{uuid4()}", json={"store_name": "Магазин"})
    assert response.status_code == 401
