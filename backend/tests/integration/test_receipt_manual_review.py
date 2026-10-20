from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Category, Receipt, ReceiptItem, User
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


@pytest.fixture
def review_item(review_receipt):
    with SessionLocal.begin() as session:
        category = Category(category_name="Продукты")
        item = ReceiptItem(
            receipt_id=review_receipt,
            category=category,
            raw_name="МОЛОКО OCR",
            normalized_name="молоко",
            quantity=Decimal(2),
            unit="шт",
            unit_price=Decimal("50.00"),
            total_price=Decimal("100.00"),
            confidence=0.8,
        )
        session.add(item)
        session.flush()
        return review_receipt, item.receipt_item_id


def item_url(review_item):
    receipt_id, item_id = review_item
    return f"/api/receipts/{receipt_id}/items/{item_id}"


def test_edit_item_name_quantity_prices_and_category(review_item, client):
    receipt_id, item_id = review_item
    with SessionLocal.begin() as session:
        category = Category(category_name="Молочные продукты")
        session.add(category)
        session.flush()
        category_id = category.category_id
    payload = {
        "raw_name": "  Молоко 3,2%  ",
        "normalized_name": "  молоко 3,2%  ",
        "quantity": "0.432",
        "unit_price": "125.50",
        "total_price": "54.22",
        "category_id": str(category_id),
    }
    response = client.patch(item_url(review_item), json=payload)
    assert response.status_code == 200
    detail = client.get(f"/api/receipts/{receipt_id}").json()
    for body in (response.json(), detail["items"][0]):
        assert body["raw_name"] == "Молоко 3,2%"
        assert body["normalized_name"] == "молоко 3,2%"
        assert Decimal(body["quantity"]) == Decimal("0.432")
        assert body["unit_price"] == "125.50"
        assert body["total_price"] == "54.22"
        assert body["category_id"] == str(category_id)
    assert detail["status"] == "need_review"
    assert detail["raw_ocr_text"] == "Исходный текст"
    with SessionLocal() as session:
        item = session.get(ReceiptItem, item_id)
        assert item.normalized_name == "молоко 3,2%"
        assert item.category_id == category_id
        assert item.quantity == Decimal("0.432")
        assert item.unit_price == Decimal("125.50")
        assert item.total_price == Decimal("54.22")
        assert session.get(Receipt, receipt_id).items_revision == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_name", "Другое название"),
        ("normalized_name", "исправленное название"),
        ("normalized_name", None),
        ("quantity", "0.001"),
        ("quantity", "999999999999.999"),
        ("unit_price", "0.00"),
        ("unit_price", "9999999999.99"),
        ("unit_price", None),
        ("total_price", "0.00"),
        ("total_price", "35.67"),
        ("total_price", None),
        ("category_id", None),
    ],
)
def test_edit_item_preserves_omitted_fields(review_item, client, field, value):
    receipt_id, _ = review_item
    url = f"/api/receipts/{receipt_id}"
    before = client.get(url).json()["items"][0]
    response = client.patch(item_url(review_item), json={field: value})
    assert response.status_code == 200
    after = client.get(url).json()["items"][0]
    if field in {"quantity", "unit_price", "total_price"} and value is not None:
        assert Decimal(after[field]) == Decimal(value)
    else:
        assert after[field] == value
    changed = {field, "updated_at"}
    if field in {"raw_name", "normalized_name"}:
        changed.add("category_source")
        changed |= {
            "suggested_category_id",
            "category_rule_version",
            "category_match",
            "category_input",
        }
    if field == "category_id":
        changed.add("category_confirmed_at")
        changed.add("category_source")
    for omitted in before.keys() - changed:
        assert after[omitted] == before[omitted]
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items_revision == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"raw_name": None},
        {"raw_name": ""},
        {"raw_name": " \t\n "},
        {"raw_name": "а" * 257},
        {"normalized_name": "   "},
        {"normalized_name": "а" * 257},
        {"quantity": None},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"quantity": "0.0001"},
        {"quantity": "1000000000000"},
        {"quantity": "NaN"},
        {"unit_price": "-0.01"},
        {"unit_price": "1.234"},
        {"unit_price": "10000000000"},
        {"unit_price": "Infinity"},
        {"total_price": "-1"},
        {"total_price": "1.234"},
        {"total_price": "10000000000"},
        {"total_price": "NaN"},
        {"category_id": "invalid-uuid"},
        {"receipt_id": str(uuid4())},
        {"raw_name": "Не сохранять", "quantity": "-1"},
    ],
)
def test_invalid_item_edit_is_atomic(review_item, client, payload):
    receipt_id, _ = review_item
    detail_url = f"/api/receipts/{receipt_id}"
    before = client.get(detail_url).json()
    assert client.patch(item_url(review_item), json=payload).status_code == 422
    assert client.get(detail_url).json() == before
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items_revision == 0


def test_unknown_category_does_not_save_other_item_changes(review_item, client):
    receipt_id, _ = review_item
    detail_url = f"/api/receipts/{receipt_id}"
    before = client.get(detail_url).json()
    response = client.patch(
        item_url(review_item),
        json={"normalized_name": "Не сохранять", "category_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Category not found"}
    assert client.get(detail_url).json() == before
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items_revision == 0


def test_item_must_belong_to_receipt_in_url(review_item, client):
    receipt_id, item_id = review_item
    with SessionLocal.begin() as session:
        owner_id = session.get(Receipt, receipt_id).receipt_user_id
        other = Receipt(receipt_user_id=owner_id, image_object_key="review/other.jpg")
        session.add(other)
        session.flush()
        other_id = other.receipt_id
    response = client.patch(
        f"/api/receipts/{other_id}/items/{item_id}", json={"raw_name": "Не сохранять"}
    )
    assert response.status_code == 404
    with SessionLocal() as session:
        assert session.get(ReceiptItem, item_id).raw_name == "МОЛОКО OCR"
        assert session.get(Receipt, receipt_id).items_revision == 0
        assert session.get(Receipt, other_id).items_revision == 0
