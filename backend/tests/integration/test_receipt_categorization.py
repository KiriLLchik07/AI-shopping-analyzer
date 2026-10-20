from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete

from backend.app.api.dependencies.auth import get_current_user
from backend.app.categorization.catalog import DEFAULT_CATEGORIES, default_category_id
from backend.app.categorization.rules import RULE_VERSION
from backend.app.core.exceptions import ConflictError
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Category, Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.ocr import OcrResult
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.workers import jobs

TEXT = "МАГНИТ\nМОЛОКО 100.00*1шт=100.00\nИТОГ 100.00"
pytestmark = pytest.mark.integration


@pytest.fixture
def owner_receipt(client, monkeypatch):
    with SessionLocal.begin() as session:
        owner = User(
            user_name="Category",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(user=owner, image_object_key="categories/test.jpg")
        session.add(receipt)
        session.flush()
        receipt_id = receipt.receipt_id
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    return receipt_id, owner.user_id


def parse(text=TEXT):
    return UnconfiguredReceiptPipeline(Mock(), Mock()).parse(text)


def process(receipt_id):
    assert (
        ReceiptProcessingService(SessionLocal).save_result(receipt_id, parse())
        == SaveProcessingOutcome.SAVED
    )


def item_body(client, receipt_id):
    return client.get(f"/api/receipts/{receipt_id}").json()["items"][0]


def test_default_catalog_is_available(client, owner_receipt):
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert {row["category_name"] for row in response.json()} == set(DEFAULT_CATEGORIES)


def test_worker_saves_prediction_and_keeps_it_unconfirmed(
    owner_receipt, client, monkeypatch
):
    receipt_id, _ = owner_receipt
    storage, normalizer, provider = Mock(), Mock(), Mock()
    storage.download.return_value = b"original"
    normalizer.normalize_with_report.return_value = Mock(
        image=b"normalized", report=None
    )
    provider.recognize.return_value = OcrResult(raw_text=TEXT, confidence=0.9)
    pipeline = UnconfiguredReceiptPipeline(storage, normalizer, provider)
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline)
    jobs.process_receipt(str(receipt_id))
    body = item_body(client, receipt_id)
    assert (
        body["category_id"]
        == body["suggested_category_id"]
        == str(default_category_id("продукты"))
    )
    assert body["category_rule_version"] == RULE_VERSION
    assert body["category_match"] is not None
    assert body["category_input"] == "молоко"
    assert body["category_confirmed_at"] is None
    assert body["category_source"] == "automatic"
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.items[0].suggested_category_id == default_category_id("продукты")
    assert (
        ReceiptProcessingService(SessionLocal).save_result(receipt_id, parse())
        == SaveProcessingOutcome.ALREADY_SAVED
    )
    assert item_body(client, receipt_id) == body


def test_manual_create_stores_suggestion_separately_from_label(owner_receipt, client):
    receipt_id, _ = owner_receipt
    response = client.post(
        f"/api/receipts/{receipt_id}/items",
        json={
            "raw_name": "Молоко",
            "quantity": 1,
            "category_id": str(default_category_id("сладкое")),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["suggested_category_id"] == str(default_category_id("продукты"))
    assert body["category_id"] == str(default_category_id("сладкое"))
    assert body["category_confirmed_at"] is not None
    assert body["category_source"] == "manual"


def test_manual_choice_preserves_suggestion_and_needs_explicit_reprocess_consent(
    owner_receipt, client
):
    receipt_id, owner_id = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    url = f"/api/receipts/{receipt_id}/items/{body['receipt_item_id']}"
    response = client.patch(
        url, json={"category_id": str(default_category_id("напитки"))}
    )
    assert response.status_code == 200
    chosen = response.json()
    assert chosen["suggested_category_id"] == body["suggested_category_id"]
    assert chosen["category_id"] == str(default_category_id("напитки"))
    assert chosen["category_confirmed_at"] is not None
    assert chosen["category_source"] == "manual"
    service = ReceiptProcessingService(SessionLocal)
    assert (
        service.save_result(receipt_id, parse()) == SaveProcessingOutcome.ALREADY_SAVED
    )
    with pytest.raises(ConflictError):
        service.prepare_process(receipt_id, owner_id, False)
    assert item_body(client, receipt_id) == chosen
    ticket = service.prepare_process(receipt_id, owner_id, True)
    assert service.start_processing(receipt_id, ticket.processing_version) is not None
    assert (
        service.save_result(receipt_id, parse(), ticket.processing_version)
        == SaveProcessingOutcome.SAVED
    )
    replaced = item_body(client, receipt_id)
    assert replaced["category_id"] == str(default_category_id("продукты"))
    assert replaced["category_confirmed_at"] is None
    assert replaced["category_source"] == "automatic"


@pytest.mark.parametrize("field", ["raw_name", "normalized_name"])
@pytest.mark.parametrize("manual", [False, True])
def test_rename_updates_prediction_but_keeps_manual_category(
    owner_receipt, client, field, manual
):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    url = f"/api/receipts/{receipt_id}/items/{body['receipt_item_id']}"
    if manual:
        body = client.patch(
            url, json={"category_id": str(default_category_id("сладкое"))}
        ).json()
    response = client.patch(url, json={field: "Чипсы сырные"})
    assert response.status_code == 200
    updated = response.json()
    assert updated["suggested_category_id"] == str(default_category_id("снеки"))
    assert updated["category_input"] == "чипсы сырные"
    assert updated["category_id"] == (
        str(default_category_id("сладкое"))
        if manual
        else str(default_category_id("снеки"))
    )
    assert updated["category_confirmed_at"] == body["category_confirmed_at"]


def test_explicit_clear_is_kept_after_rename(owner_receipt, client):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    url = f"/api/receipts/{receipt_id}/items/{body['receipt_item_id']}"
    cleared = client.patch(url, json={"category_id": None}).json()
    assert cleared["category_id"] is None
    assert cleared["category_confirmed_at"] is not None
    renamed = client.patch(url, json={"normalized_name": "Кефир"}).json()
    assert renamed["category_id"] is None
    assert renamed["suggested_category_id"] == str(default_category_id("продукты"))
    assert renamed["category_confirmed_at"] == cleared["category_confirmed_at"]


def test_explicit_null_on_create_differs_from_omitted_category(owner_receipt, client):
    receipt_id, _ = owner_receipt
    url = f"/api/receipts/{receipt_id}/items"
    payload = {"raw_name": "Неизвестный товар", "quantity": 1}
    automatic = client.post(url, json=payload).json()
    manual = client.post(url, json=payload | {"category_id": None}).json()
    fallback = str(default_category_id("прочее"))
    assert automatic["category_id"] == automatic["suggested_category_id"] == fallback
    assert automatic["category_match"] is None
    assert automatic["category_confirmed_at"] is None
    assert manual["category_id"] is None
    assert manual["suggested_category_id"] == fallback
    assert manual["category_confirmed_at"] is not None


def test_selecting_same_category_is_recorded_as_human_choice(owner_receipt, client):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{body['receipt_item_id']}",
        json={"category_id": body["category_id"]},
    )
    assert response.status_code == 200
    assert response.json()["category_confirmed_at"] is not None
    assert response.json()["suggested_category_id"] == body["suggested_category_id"]


@pytest.mark.parametrize(
    "field",
    [
        "suggested_category_id",
        "category_rule_version",
        "category_match",
        "category_input",
        "category_confirmed_at",
        "category_source",
    ],
)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_client_cannot_forge_prediction_or_confirmation(
    owner_receipt, client, field, method
):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    payload = {field: None}
    url = f"/api/receipts/{receipt_id}/items"
    if method == "post":
        response = client.post(url, json=payload | {"raw_name": "Товар", "quantity": 1})
    else:
        response = client.patch(f"{url}/{body['receipt_item_id']}", json=payload)
    assert response.status_code == 422
    assert item_body(client, receipt_id) == body


def test_missing_default_catalog_rolls_back_result(owner_receipt):
    receipt_id, _ = owner_receipt
    with SessionLocal.begin() as session:
        session.execute(
            delete(Category).where(
                Category.category_id == default_category_id("продукты")
            )
        )
    with pytest.raises(RuntimeError, match="apply database migrations"):
        ReceiptProcessingService(SessionLocal).save_result(receipt_id, parse())
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.items == []
        assert receipt.processing_result_saved_at is None


def test_old_category_is_preserved_without_inventing_manual_confirmation(
    owner_receipt, client
):
    receipt_id, _ = owner_receipt
    with SessionLocal.begin() as session:
        item = ReceiptItem(
            receipt_id=receipt_id,
            raw_name="Молоко",
            quantity=1,
            category_id=default_category_id("напитки"),
        )
        session.add(item)
        session.flush()
        item_id = item.receipt_item_id
    body = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}", json={"raw_name": "Хлеб"}
    ).json()
    assert body["category_id"] == str(default_category_id("напитки"))
    assert body["suggested_category_id"] == str(default_category_id("продукты"))
    assert body["category_confirmed_at"] is None
    assert body["category_source"] == "legacy"
    body = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}", json={"raw_name": "Чипсы"}
    ).json()
    assert body["category_id"] == str(default_category_id("напитки"))
    assert body["suggested_category_id"] == str(default_category_id("снеки"))
    assert body["category_source"] == "legacy"


def test_removing_category_clears_both_foreign_keys(owner_receipt, client):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    with SessionLocal.begin() as session:
        session.execute(
            delete(Category).where(
                Category.category_id == default_category_id("продукты")
            )
        )
    body = item_body(client, receipt_id)
    assert body["category_id"] is body["suggested_category_id"] is None


def test_receipt_confirmation_does_not_invent_explicit_category_label(
    owner_receipt, client
):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    assert client.post(f"/api/receipts/{receipt_id}/confirm").status_code == 200
    body = item_body(client, receipt_id)
    assert body["category_source"] == "automatic"
    assert body["category_confirmed_at"] is None


def test_invalid_manual_category_is_atomic(owner_receipt, client):
    receipt_id, _ = owner_receipt
    process(receipt_id)
    body = item_body(client, receipt_id)
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{body['receipt_item_id']}",
        json={"normalized_name": "Чипсы", "category_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert item_body(client, receipt_id) == body
