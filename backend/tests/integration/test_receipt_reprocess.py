from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api import receipts as receipts_api
from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.exceptions import ConflictError, ReceiptProcessingConflictError
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
    ReceiptItemUpdateRequest,
)
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.services.receipt_service import ReceiptService
from backend.app.workers import jobs
from backend.app.workers import queue as queue_module

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
        receipt = Receipt(user=user, image_object_key="reprocess/test.jpg")
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
            "status": receipt.status,
            "error": receipt.processing_error_code,
            "revision": receipt.items_revision,
            "text": receipt.raw_ocr_text,
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


def test_endpoint_accepts_failed_receipt_and_commits_before_enqueue(
    receipt_owner, owner_client, monkeypatch
):
    receipt_id, _ = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.start_processing(receipt_id)
    service.mark_failed(receipt_id)
    calls = []

    def enqueue(receipt_id, processing_version):
        state = snapshot(receipt_id)
        assert state["version"] == processing_version == 2
        assert state["status"] == ReceiptStatus.UPLOADED
        assert state["error"] is None
        calls.append((receipt_id, processing_version))
        return "test-job"

    monkeypatch.setattr(receipts_api, "enqueue_receipt", enqueue)
    response = owner_client.post(f"/api/receipts/{receipt_id}/reprocess")
    assert response.status_code == 202
    assert response.json() == {
        "receipt_id": str(receipt_id),
        "processing_version": 2,
        "job_id": "test-job",
    }
    assert owner_client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409
    assert calls == [(receipt_id, 2)]


@pytest.mark.parametrize(
    "status", [ReceiptStatus.NEED_REVIEW, ReceiptStatus.COMPLETED, ReceiptStatus.FAILED]
)
def test_existing_items_require_consent_and_remain_until_success(
    receipt_owner, owner_client, monkeypatch, status
):
    receipt_id, _ = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, result())
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = status
    original = snapshot(receipt_id)
    monkeypatch.setattr(receipts_api, "enqueue_receipt", lambda *a, **kw: "test-job")
    assert owner_client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409
    assert snapshot(receipt_id) == original
    response = owner_client.post(
        f"/api/receipts/{receipt_id}/reprocess", json={"replace_items": True}
    )
    assert response.status_code == 202
    assert snapshot(receipt_id)["items"] == original["items"]
    monkeypatch.setattr(jobs, "get_receipt_pipeline", TestPipeline)
    jobs.process_receipt(str(receipt_id), 2)
    saved = snapshot(receipt_id)
    assert list(saved["items"].values()) == ["Replacement"]
    assert set(saved["items"]).isdisjoint(original["items"])
    jobs.process_receipt(str(receipt_id), 2)
    assert (
        service.save_result(receipt_id, result(), 2)
        == SaveProcessingOutcome.ALREADY_SAVED
    )
    assert snapshot(receipt_id) == saved


@pytest.mark.parametrize(
    "status",
    [
        ReceiptStatus.UPLOADED,
        ReceiptStatus.PREPROCESSING,
        ReceiptStatus.OCR_PROCESSING,
        ReceiptStatus.PARSING,
    ],
)
def test_pending_receipt_rejected(receipt_owner, owner_client, monkeypatch, status):
    receipt_id, _ = receipt_owner
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = status
    monkeypatch.setattr(
        receipts_api,
        "enqueue_receipt",
        lambda *a, **kw: pytest.fail("Unexpected enqueue"),
    )
    assert owner_client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409
    assert snapshot(receipt_id)["version"] == 1


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
    service.save_result(receipt_id, result())
    service.prepare_process(receipt_id, owner.user_id, True)
    assert service.start_processing(receipt_id, 2) is not None
    before = snapshot(receipt_id)
    monkeypatch.setattr(
        jobs, "get_receipt_pipeline", lambda: pytest.fail("Stale job ran pipeline")
    )
    jobs.process_receipt(str(receipt_id), 1)
    assert (
        service.advance_status(
            receipt_id, ReceiptStatus.PREPROCESSING, ReceiptStatus.OCR_PROCESSING, 1
        )
        is False
    )
    assert service.mark_failed(receipt_id, RuntimeError("Old error"), 1) is False
    assert (
        service.save_result(receipt_id, result(), 1) == SaveProcessingOutcome.STALE_JOB
    )
    service.mark_enqueue_unconfirmed(receipt_id, 1)
    assert snapshot(receipt_id) == before


@pytest.mark.parametrize("mutation", ["create", "update", "delete"])
def test_manual_edits_during_processing_are_preserved(receipt_owner, mutation):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, result())
    service.prepare_process(receipt_id, owner.user_id, True)
    service.start_processing(receipt_id, 2)
    item_id = next(iter(snapshot(receipt_id)["items"]))
    with SessionLocal() as session:
        manual = ReceiptService(session)
        if mutation == "create":
            manual.create_receipt_item(
                ReceiptItemCreateRequest(raw_name="Manual", quantity=1),
                receipt_id,
                owner.user_id,
            )
        elif mutation == "update":
            manual.update_receipt_item(
                ReceiptItemUpdateRequest(raw_name="Manual"),
                receipt_id,
                item_id,
                owner.user_id,
            )
        else:
            manual.delete_receipt_item(receipt_id, item_id, owner.user_id)
    before = snapshot(receipt_id)
    assert before["revision"] == 2
    with pytest.raises(ReceiptProcessingConflictError):
        service.save_result(receipt_id, result("Replacement"), 2)
    assert snapshot(receipt_id) == before


def test_failed_replacement_rolls_back_deletion(receipt_owner, monkeypatch):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, result())
    original = snapshot(receipt_id)
    service.prepare_process(receipt_id, owner.user_id, True)

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
    assert failed["status"] == ReceiptStatus.FAILED
    assert failed["items"] == original["items"]
    assert failed["text"] == original["text"]
    assert failed["revision"] == original["revision"]
    assert failed["saved_at"] is None


@pytest.mark.parametrize("worker_started", [False, True])
def test_enqueue_failure_is_safe_and_does_not_overwrite_running_job(
    receipt_owner, owner_client, monkeypatch, worker_started
):
    receipt_id, _ = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, result())
    original_items = snapshot(receipt_id)["items"]

    def enqueue(receipt_id, processing_version):
        if worker_started:
            service.start_processing(receipt_id, processing_version)
        raise RedisConnectionError("SECRET-REDIS-ADDRESS")

    monkeypatch.setattr(receipts_api, "enqueue_receipt", enqueue)
    response = owner_client.post(
        f"/api/receipts/{receipt_id}/reprocess", json={"replace_items": True}
    )
    assert response.status_code == 503
    assert "SECRET-REDIS-ADDRESS" not in response.text
    state = snapshot(receipt_id)
    assert state["items"] == original_items
    assert state["status"] == (
        ReceiptStatus.PREPROCESSING if worker_started else ReceiptStatus.FAILED
    )
    assert state["error"] == (None if worker_started else "receipt_enqueue_unconfirmed")


def test_concurrent_reprocess_requests_only_prepare_one_version(receipt_owner):
    receipt_id, owner = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, result())
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
    job_id = queue_module.enqueue_receipt(receipt_id, 7)
    job = queue_module.receipt_queue.fetch_job(job_id)
    assert job.func_name == "backend.app.workers.jobs.process_receipt"
    assert job.args == (str(receipt_id), 7)
    assert job.kwargs == {}
