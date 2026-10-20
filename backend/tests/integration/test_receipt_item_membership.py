from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from backend.app.api.dependencies.auth import get_current_user
from backend.app.categorization.catalog import default_category_id
from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Category, Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.services.receipt_processing_service import ReceiptProcessingService

pytestmark = pytest.mark.integration


@pytest.fixture
def receipt_item(client, monkeypatch):
    with SessionLocal.begin() as session:
        owner = User(
            user_name="Items",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(
            user=owner,
            image_object_key="review/items.jpg",
            status=ReceiptStatus.NEED_REVIEW,
            raw_ocr_text="Исходный OCR",
            total_amount=Decimal("100.00"),
        )
        item = ReceiptItem(receipt=receipt, raw_name="Исходная позиция", quantity=1)
        session.add(item)
        session.flush()
        ids = receipt.receipt_id, item.receipt_item_id, owner.user_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    return ids


def test_add_item_persists_all_values_and_keeps_existing_position(receipt_item, client):
    receipt_id, original_id, _ = receipt_item
    with SessionLocal.begin() as session:
        category = Category(category_name="Фрукты")
        session.add(category)
        session.flush()
        category_id = category.category_id
    url = f"/api/receipts/{receipt_id}"
    response = client.post(
        f"{url}/items",
        json={
            "raw_name": "  Яблоки  ",
            "normalized_name": "  яблоки  ",
            "quantity": "0.432",
            "unit": "кг",
            "unit_price": "125.50",
            "total_price": "54.22",
            "discount_amount": "1.00",
            "category_id": str(category_id),
        },
    )
    assert response.status_code == 201
    body = response.json()
    item_id = UUID(body["receipt_item_id"])
    assert body["raw_name"] == "Яблоки"
    assert body["normalized_name"] == "яблоки"
    assert Decimal(body["quantity"]) == Decimal("0.432")
    assert body["unit_price"] == "125.50"
    assert body["total_price"] == "54.22"
    assert body["discount_amount"] == "1.00"
    assert body["category_id"] == str(category_id)
    assert body["confidence"] is None
    detail = client.get(url).json()
    assert {item["receipt_item_id"] for item in detail["items"]} == {
        str(original_id),
        str(item_id),
    }
    assert detail["status"] == "need_review"
    assert detail["raw_ocr_text"] == "Исходный OCR"
    assert detail["total_amount"] == "100.00"
    with SessionLocal() as session:
        item = session.get(ReceiptItem, item_id)
        assert item.receipt_id == receipt_id
        assert item.quantity == Decimal("0.432")
        assert item.category_id == category_id
        assert session.get(Receipt, receipt_id).items_revision == 1


def test_minimal_item_allows_unknown_prices_and_suggests_fallback(receipt_item, client):
    receipt_id, _, _ = receipt_item
    response = client.post(
        f"/api/receipts/{receipt_id}/items", json={"raw_name": "Товар", "quantity": 1}
    )
    assert response.status_code == 201
    assert response.json()["unit_price"] is None
    assert response.json()["total_price"] is None
    assert response.json()["category_id"] == str(default_category_id("прочее"))
    assert response.json()["category_confirmed_at"] is None
    assert response.json()["discount_amount"] == "0.00"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"raw_name": "Товар"},
        {"raw_name": "   ", "quantity": 1},
        {"raw_name": "Товар", "quantity": None},
        {"raw_name": "Товар", "quantity": "-1"},
        {"raw_name": "Товар", "quantity": "0"},
        {"raw_name": "Товар", "quantity": "0.0001"},
        {"raw_name": "Товар", "quantity": 1, "normalized_name": "   "},
        {"raw_name": "Товар", "quantity": 1, "unit_price": "-1"},
        {"raw_name": "Товар", "quantity": 1, "total_price": "1.234"},
        {"raw_name": "Товар", "quantity": 1, "total_price": "10000000000"},
        {"raw_name": "Товар", "quantity": 1, "discount_amount": "1.234"},
        {"raw_name": "Товар", "quantity": 1, "discount_amount": "10000000000"},
        {"raw_name": "Товар", "quantity": 1, "discount_amount": "NaN"},
        {"raw_name": "Товар", "quantity": 1, "weight": "0.001"},
        {"raw_name": "Товар", "quantity": 1, "weight": "10000000000"},
    ],
)
def test_invalid_add_does_not_change_receipt(receipt_item, client, payload):
    receipt_id, _, _ = receipt_item
    url = f"/api/receipts/{receipt_id}"
    before = client.get(url).json()
    assert client.post(f"{url}/items", json=payload).status_code == 422
    assert client.get(url).json() == before
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items_revision == 0


def test_delete_removes_only_target_and_repeated_delete_returns_404(
    receipt_item, client
):
    receipt_id, item_id, _ = receipt_item
    with SessionLocal.begin() as session:
        remaining = ReceiptItem(receipt_id=receipt_id, raw_name="Оставить", quantity=1)
        session.add(remaining)
        session.flush()
        remaining_id = remaining.receipt_item_id
    url = f"/api/receipts/{receipt_id}"
    response = client.delete(f"{url}/items/{item_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.delete(f"{url}/items/{item_id}").status_code == 404
    detail = client.get(url).json()
    assert [item["receipt_item_id"] for item in detail["items"]] == [str(remaining_id)]
    assert detail["status"] == "need_review"
    assert detail["total_amount"] == "100.00"
    with SessionLocal() as session:
        assert session.get(ReceiptItem, item_id) is None
        assert session.get(ReceiptItem, remaining_id) is not None
        assert session.get(Receipt, receipt_id).items_revision == 1


def test_delete_last_item_keeps_receipt(receipt_item, client):
    receipt_id, item_id, _ = receipt_item
    url = f"/api/receipts/{receipt_id}"
    assert client.delete(f"{url}/items/{item_id}").status_code == 204
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_cannot_delete_item_through_another_receipt(receipt_item, client):
    receipt_id, item_id, owner_id = receipt_item
    with SessionLocal.begin() as session:
        other = Receipt(receipt_user_id=owner_id, image_object_key="review/other.jpg")
        session.add(other)
        session.flush()
        other_id = other.receipt_id
    assert client.delete(f"/api/receipts/{other_id}/items/{item_id}").status_code == 404
    with SessionLocal() as session:
        assert session.get(ReceiptItem, item_id) is not None
        assert session.get(Receipt, receipt_id).items_revision == 0
        assert session.get(Receipt, other_id).items_revision == 0


@pytest.mark.parametrize("operation", ["add", "delete"])
def test_membership_change_blocks_running_worker_result(
    receipt_item, client, operation
):
    receipt_id, item_id, owner_id = receipt_item
    service = ReceiptProcessingService(SessionLocal)
    ticket = service.prepare_process(receipt_id, owner_id, replace_items=True)
    assert service.start_processing(receipt_id, ticket.processing_version) is not None
    url = f"/api/receipts/{receipt_id}"
    if operation == "add":
        assert (
            client.post(
                f"{url}/items", json={"raw_name": "Ручная позиция", "quantity": 1}
            ).status_code
            == 201
        )
    else:
        assert client.delete(f"{url}/items/{item_id}").status_code == 204
    before = client.get(url).json()["items"]
    with pytest.raises(ReceiptProcessingConflictError):
        service.save_result(
            receipt_id, ReceiptProcessingResult(items=()), ticket.processing_version
        )
    assert client.get(url).json()["items"] == before


def test_membership_changes_require_owner(receipt_item, client, monkeypatch):
    receipt_id, item_id, _ = receipt_item
    with SessionLocal.begin() as session:
        other = User(
            user_name="Other",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        session.add(other)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: other)
    url = f"/api/receipts/{receipt_id}"
    assert (
        client.post(
            f"{url}/items", json={"raw_name": "Чужой", "quantity": 1}
        ).status_code
        == 404
    )
    assert client.delete(f"{url}/items/{item_id}").status_code == 404
    with SessionLocal() as session:
        assert len(session.get(Receipt, receipt_id).items) == 1
        assert session.get(Receipt, receipt_id).items_revision == 0


def test_membership_changes_require_authentication(client):
    url = f"/api/receipts/{uuid4()}/items"
    assert (
        client.post(url, json={"raw_name": "Товар", "quantity": 1}).status_code == 401
    )
    assert client.delete(f"{url}/{uuid4()}").status_code == 401
