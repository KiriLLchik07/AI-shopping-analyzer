from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.services.receipt_processing_service import ReceiptProcessingService
from backend.app.services.receipt_service import ReceiptService

pytestmark = pytest.mark.integration


@pytest.fixture
def review_receipt(client, monkeypatch):
    with SessionLocal.begin() as session:
        owner = User(
            user_name="Confirm",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(
            user=owner,
            image_object_key="confirm/test.jpg",
            status=ReceiptStatus.NEED_REVIEW,
            store_name="Магазин",
            purchase_datetime=datetime(2026, 10, 20, 12, tzinfo=UTC),
            total_amount=Decimal("100.00"),
            raw_ocr_text="Исходный OCR",
            processing_result_saved_at=datetime.now(UTC),
        )
        item = ReceiptItem(
            receipt=receipt,
            raw_name="Товар",
            normalized_name="товар",
            quantity=1,
            unit_price=Decimal("100.00"),
            total_price=Decimal("100.00"),
        )
        session.add(item)
        session.flush()
        ids = receipt.receipt_id, item.receipt_item_id, owner.user_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    return ids


def test_confirm_persists_status_and_repeated_request_is_idempotent(
    review_receipt, client
):
    receipt_id, item_id, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    before = client.get(url).json()
    response = client.post(f"{url}/confirm")
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["status"] == "completed"
    assert confirmed["store_name"] == before["store_name"]
    assert confirmed["total_amount"] == before["total_amount"]
    assert confirmed["raw_ocr_text"] == before["raw_ocr_text"]
    assert client.get(url).json()["items"] == before["items"]
    repeated = client.post(f"{url}/confirm")
    assert repeated.status_code == 200
    assert repeated.json() == confirmed
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.COMPLETED
        assert receipt.items_revision == 0
        assert session.get(ReceiptItem, item_id) is not None


@pytest.mark.parametrize(
    "status",
    [
        ReceiptStatus.UPLOADED,
        ReceiptStatus.PREPROCESSING,
        ReceiptStatus.OCR_PROCESSING,
        ReceiptStatus.PARSING,
        ReceiptStatus.FAILED,
    ],
)
def test_confirmation_rejects_receipts_not_ready_for_review(
    review_receipt, client, status
):
    receipt_id, _, _ = review_receipt
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = status
    response = client.post(f"/api/receipts/{receipt_id}/confirm")
    assert response.status_code == 409
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).status == status


def test_confirmation_requires_owner_and_hides_unknown_receipt(
    review_receipt, client, monkeypatch
):
    receipt_id, _, _ = review_receipt
    with SessionLocal.begin() as session:
        other = User(
            user_name="Other",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        session.add(other)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: other)
    for target in (receipt_id, uuid4()):
        response = client.post(f"/api/receipts/{target}/confirm")
        assert response.status_code == 404
        assert response.json() == {"detail": "Receipt not found"}
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).status == ReceiptStatus.NEED_REVIEW


def test_confirmation_requires_authentication(client):
    assert client.post(f"/api/receipts/{uuid4()}/confirm").status_code == 401


@pytest.mark.parametrize(
    "mutation", ["receipt", "update_item", "add_item", "delete_item"]
)
def test_manual_edit_requires_confirmation_again(review_receipt, client, mutation):
    receipt_id, item_id, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.post(f"{url}/confirm").status_code == 200
    if mutation == "receipt":
        response = client.patch(url, json={"store_name": "Другой магазин"})
    elif mutation == "update_item":
        response = client.patch(
            f"{url}/items/{item_id}", json={"normalized_name": "Правка"}
        )
    elif mutation == "add_item":
        response = client.post(
            f"{url}/items",
            json={
                "raw_name": "Новый",
                "quantity": 1,
                "unit_price": "0",
                "total_price": "0",
            },
        )
    else:
        response = client.delete(f"{url}/items/{item_id}")
    assert response.status_code in {200, 201, 204}
    assert client.get(url).json()["status"] == "need_review"
    if mutation == "delete_item":
        assert client.post(f"{url}/confirm").status_code == 400
        assert (
            client.post(
                f"{url}/items",
                json={
                    "raw_name": "Замена",
                    "quantity": 1,
                    "unit_price": "100",
                    "total_price": "100",
                },
            ).status_code
            == 201
        )
    assert client.post(f"{url}/confirm").json()["status"] == "completed"


def test_invalid_edit_does_not_invalidate_confirmation(review_receipt, client):
    receipt_id, item_id, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.post(f"{url}/confirm").status_code == 200
    assert client.patch(url, json={"total_amount": "-1"}).status_code == 422
    assert (
        client.patch(f"{url}/items/{item_id}", json={"quantity": "-1"}).status_code
        == 422
    )
    assert client.get(url).json()["status"] == "completed"


def test_reprocessing_requires_new_confirmation(review_receipt, client):
    receipt_id, _, owner_id = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.post(f"{url}/confirm").status_code == 200
    ReceiptProcessingService(SessionLocal).prepare_process(receipt_id, owner_id, True)
    assert client.get(url).json()["status"] == "uploaded"
    assert client.post(f"{url}/confirm").status_code == 409


def test_concurrent_confirmation_is_idempotent(review_receipt):
    receipt_id, _, owner_id = review_receipt
    barrier = Barrier(2)

    def confirm():
        with SessionLocal() as session:
            barrier.wait(timeout=5)
            receipt = ReceiptService(session).confirm_receipt(receipt_id, owner_id)
            return receipt.status, receipt.updated_at

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert results[0][0] == ReceiptStatus.COMPLETED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "2"),
        ("unit_price", "90"),
        ("total_price", "99.94"),
        ("unit_price", None),
        ("total_price", None),
    ],
)
def test_inconsistent_or_partial_item_cannot_be_confirmed(
    review_receipt, client, field, value
):
    receipt_id, item_id, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert (
        client.patch(f"{url}/items/{item_id}", json={field: value}).status_code == 200
    )
    before = client.get(url).json()
    response = client.post(f"{url}/confirm")
    assert response.status_code == 400
    assert "Позиция" in response.json()["detail"]
    assert client.get(url).json() == before


def test_receipt_total_must_match_current_items_and_can_be_fixed(
    review_receipt, client
):
    receipt_id, _, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.patch(url, json={"total_amount": "101"}).status_code == 200
    response = client.post(f"{url}/confirm")
    assert response.status_code == 400
    assert "Сумма позиций" in response.json()["detail"]
    assert client.get(url).json()["status"] == "need_review"
    assert client.patch(url, json={"total_amount": "100"}).status_code == 200
    assert client.post(f"{url}/confirm").json()["status"] == "completed"


def test_missing_receipt_total_cannot_be_confirmed(review_receipt, client):
    receipt_id, _, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.patch(url, json={"total_amount": None}).status_code == 200
    assert client.post(f"{url}/confirm").status_code == 400
    assert client.get(url).json()["status"] == "need_review"


def test_missing_ocr_quantity_cannot_be_confirmed(review_receipt, client):
    receipt_id, item_id, _ = review_receipt
    with SessionLocal.begin() as session:
        session.get(ReceiptItem, item_id).quantity = None
    assert client.post(f"/api/receipts/{receipt_id}/confirm").status_code == 400


def test_confirmation_uses_live_values_and_ignores_stale_parsing_report(
    review_receipt, client
):
    receipt_id, item_id, _ = review_receipt
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).parsing_report = {
            "total_amount": "1000.00",
            "warnings": ["Старое расхождение"],
        }
    url = f"/api/receipts/{receipt_id}"
    assert (
        client.patch(
            f"{url}/items/{item_id}", json={"discount_amount": "20"}
        ).status_code
        == 200
    )
    assert client.post(f"{url}/confirm").status_code == 200
    assert client.get(url).json()["parsing_report"]["total_amount"] == "1000.00"


@pytest.mark.parametrize("total", ["99.95", "100.05"])
def test_confirmation_allows_configured_tolerance_at_boundary(
    review_receipt, client, total
):
    receipt_id, _, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    assert client.patch(url, json={"total_amount": total}).status_code == 200
    assert client.post(f"{url}/confirm").status_code == 200


@pytest.mark.parametrize("field", ["unit_price", "total_price", "discount_amount"])
@pytest.mark.parametrize("method", ["post", "patch"])
def test_negative_item_amounts_are_rejected_without_changes(
    review_receipt, client, field, method
):
    receipt_id, item_id, _ = review_receipt
    url = f"/api/receipts/{receipt_id}"
    before = client.get(url).json()
    payload = {field: "-0.01"}
    if method == "post":
        payload |= {"raw_name": "Нельзя сохранить", "quantity": 1}
        response = client.post(f"{url}/items", json=payload)
    else:
        response = client.patch(f"{url}/items/{item_id}", json=payload)
    assert response.status_code == 422
    assert client.get(url).json() == before


@pytest.mark.parametrize("value", ["1.234", "10000000000", "NaN", "Infinity"])
def test_invalid_discount_update_is_rejected(review_receipt, client, value):
    receipt_id, item_id, _ = review_receipt
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}", json={"discount_amount": value}
    )
    assert response.status_code == 422
