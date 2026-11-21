from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.exceptions import ConflictError
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ACTIVE_PROCESSING_STATUSES, ProcessingStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
)
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.workers import jobs
from backend.app.workers.queue import enqueue_receipt, receipt_job_id, receipt_queue
from backend.app.workers.receipt_dispatcher import advance_due_receipt

pytestmark = pytest.mark.integration


def result(name="Original"):
    return ReceiptProcessingResult(
        raw_ocr_text=name,
        items=(ReceiptItemCreateRequest(raw_name=name, quantity=1),),
    )


@pytest.fixture
def receipt_owner():
    with SessionLocal.begin() as session:
        user = User(
            user_name="Reprocess",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(
            user=user,
            image_object_key="reprocess/test.jpg",
            processing_status=ProcessingStatus.FAILED,
            ocr_due_at=None,
        )
        session.add(receipt)
        session.flush()
        return receipt.receipt_id, user


@pytest.fixture
def owner_client(receipt_owner, client, monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user, lambda: receipt_owner[1]
    )
    return client


def snapshot(receipt_id):
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        return {
            "version": receipt.processing_version,
            "status": receipt.processing_status,
            "error": receipt.processing_error_code,
            "revision": receipt.items_revision,
            "text": receipt.raw_ocr_text,
            "ocr_confidence": receipt.ocr_confidence,
            "saved_at": receipt.processing_result_saved_at,
            "items": {
                item.receipt_item_id: item.raw_name
                for item in session.scalars(
                    select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
                )
            },
        }


class TestPipeline(ReceiptPipeline):
    def preprocess(self, source):
        return b"image"

    def recognize(self, image):
        return "Replacement"

    def parse(self, raw_text):
        return result(raw_text)


def test_endpoint_persists_request_for_dispatch(receipt_owner, owner_client):
    receipt_id, _ = receipt_owner
    response = owner_client.post(f"/api/receipts/{receipt_id}/reprocess")
    assert response.status_code == 202
    assert response.json() == {
        "receipt_id": str(receipt_id),
        "processing_version": 2,
        "job_id": receipt_job_id(receipt_id, 2),
    }
    assert snapshot(receipt_id)["status"] == ProcessingStatus.PENDING_DISPATCH
    assert owner_client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409
    assert advance_due_receipt()
    assert snapshot(receipt_id)["status"] == ProcessingStatus.QUEUED


@pytest.mark.parametrize(
    "processing_status",
    sorted(ACTIVE_PROCESSING_STATUSES | {ProcessingStatus.SUCCEEDED}),
)
def test_repeat_requires_final_failure(receipt_owner, owner_client, processing_status):
    receipt_id, _ = receipt_owner
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).processing_status = processing_status
    assert owner_client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409


def test_items_require_consent_and_remain_until_success(
    receipt_owner, owner_client, monkeypatch
):
    receipt_id, _ = receipt_owner
    with SessionLocal.begin() as session:
        session.add(ReceiptItem(receipt_id=receipt_id, raw_name="Manual", quantity=1))
    original = snapshot(receipt_id)["items"]
    url = f"/api/receipts/{receipt_id}/reprocess"
    assert owner_client.post(url).status_code == 409
    assert owner_client.post(url, json={"replace_items": True}).status_code == 202
    assert snapshot(receipt_id)["items"] == original
    assert advance_due_receipt()
    monkeypatch.setattr(jobs, "get_receipt_pipeline", TestPipeline)
    jobs.process_receipt(str(receipt_id), 2)
    saved = snapshot(receipt_id)
    assert list(saved["items"].values()) == ["Replacement"]
    assert set(saved["items"]).isdisjoint(original)
    jobs.process_receipt(str(receipt_id), 2)
    assert snapshot(receipt_id) == saved


def test_authentication_and_ownership(receipt_owner, client, monkeypatch):
    receipt_id, _ = receipt_owner
    assert client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 401
    with SessionLocal.begin() as session:
        other = User(
            user_name="Other",
            user_surname="Owner",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test",
        )
        session.add(other)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: other)
    for target in (receipt_id, uuid4()):
        response = client.post(f"/api/receipts/{target}/reprocess")
        assert response.status_code == 404
    assert snapshot(receipt_id)["version"] == 1


def test_invalid_request_is_rejected(receipt_owner, owner_client):
    receipt_id, _ = receipt_owner
    for payload in ({"replace_items": "true"}, {"unexpected": True}):
        assert (
            owner_client.post(
                f"/api/receipts/{receipt_id}/reprocess", json=payload
            ).status_code
            == 422
        )
    assert owner_client.post("/api/receipts/not-a-uuid/reprocess").status_code == 422


def test_stale_job_cannot_change_current_version(receipt_owner, monkeypatch):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.prepare_process(receipt_id, owner.user_id, True)
    assert advance_due_receipt()
    assert service.start_processing(receipt_id, 2) is not None
    before = snapshot(receipt_id)
    monkeypatch.setattr(
        jobs, "get_receipt_pipeline", lambda: pytest.fail("Stale job ran pipeline")
    )
    jobs.process_receipt(str(receipt_id), 1)
    assert not service.advance_status(
        receipt_id, ProcessingStatus.PREPROCESSING, ProcessingStatus.OCR_PROCESSING, 1
    )
    assert not service.mark_failed(receipt_id, RuntimeError("Old error"), 1)
    assert (
        service.save_result(receipt_id, result(), 1) == SaveProcessingOutcome.STALE_JOB
    )
    assert snapshot(receipt_id) == before


def test_failed_replacement_rolls_back_deletion(receipt_owner, monkeypatch):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    with SessionLocal.begin() as session:
        session.add(ReceiptItem(receipt_id=receipt_id, raw_name="Original", quantity=1))
    original = snapshot(receipt_id)
    service.prepare_process(receipt_id, owner.user_id, True)
    assert advance_due_receipt()

    class InvalidPipeline(TestPipeline):
        def parse(self, raw_text):
            return ReceiptProcessingResult(
                items=(
                    ReceiptItemCreateRequest(
                        raw_name="Invalid", quantity=1, category_id=uuid4()
                    ),
                )
            )

    monkeypatch.setattr(jobs, "get_receipt_pipeline", InvalidPipeline)
    with pytest.raises(IntegrityError):
        jobs.process_receipt(str(receipt_id), 2)
    failed = snapshot(receipt_id)
    assert failed["status"] == ProcessingStatus.FAILED
    assert failed["items"] == original["items"]
    assert failed["text"] == "Replacement"
    assert failed["revision"] == original["revision"]
    assert failed["saved_at"] is None


def test_three_manual_restarts_then_manual_confirmation(receipt_owner, owner_client):
    receipt_id, _ = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    url = f"/api/receipts/{receipt_id}"
    for remaining in (2, 1, 0):
        response = owner_client.post(f"{url}/reprocess")
        assert response.status_code == 202
        version = response.json()["processing_version"]
        assert advance_due_receipt()
        assert service.start_processing(receipt_id, version)
        assert service.mark_failed(receipt_id, ValueError(), version)
        assert (
            owner_client.get(url).json()["manual_ocr_attempts_remaining"] == remaining
        )

    assert owner_client.post(f"{url}/reprocess").status_code == 409
    assert owner_client.patch(url, json={"total_amount": "100"}).status_code == 200
    item = {
        "raw_name": "Milk",
        "quantity": "1",
        "unit_price": "100",
        "total_price": "100",
    }
    assert owner_client.post(f"{url}/items", json=item).status_code == 201
    review = owner_client.post(f"{url}/review")
    assert review.json()["receipt_status"] == "needs_review"
    assert owner_client.post(f"{url}/confirm").status_code == 400
    assert (
        owner_client.patch(
            url, json={"purchase_datetime": "2026-10-21T10:00:00Z"}
        ).status_code
        == 200
    )
    confirmed = owner_client.post(f"{url}/confirm").json()
    assert confirmed["receipt_status"] == "confirmed"
    assert confirmed["processing_status"] == "failed"
    assert (
        owner_client.post(f"{url}/reprocess", json={"replace_items": True}).status_code
        == 409
    )


def test_concurrent_reprocess_requests_only_prepare_one_version(receipt_owner):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    barrier = Barrier(2)

    def prepare():
        barrier.wait(timeout=5)
        try:
            return service.prepare_process(
                receipt_id, owner.user_id, True
            ).processing_version
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(prepare) for _ in range(2)]
        assert {future.result(timeout=10) for future in futures} == {2, "conflict"}
    assert snapshot(receipt_id)["version"] == 2


def test_queue_sends_receipt_id_and_version_only(receipt_owner):
    receipt_id, _ = receipt_owner
    job_id = enqueue_receipt(receipt_id, 7, None)
    job = receipt_queue.fetch_job(job_id)
    assert job.func_name == "backend.app.workers.jobs.process_receipt"
    assert job.args == (str(receipt_id), 7)
    assert job.kwargs == {}
