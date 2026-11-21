from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PIL import Image
from redis.exceptions import ConnectionError as RedisConnectionError
from rq.job import Job

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.config import setting
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, User
from backend.app.models.enums import ProcessingStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.storage.factory import get_object_storage
from backend.app.workers import receipt_dispatcher, retry_policy
from backend.app.workers.queue import (
    dispatch_queue,
    enqueue_receipt,
    queue_connection,
    receipt_job_id,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def receipt_id():
    with SessionLocal.begin() as session:
        receipt = Receipt(
            user=User(
                user_name="Recovery",
                user_surname="Test",
                user_mail=f"{uuid4()}@example.com",
                user_password_hash="test",
            ),
            image_object_key="receipts/recovery.jpg",
        )
        session.add(receipt)
        session.flush()
        return receipt.receipt_id


def make_due(receipt_id):
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).ocr_due_at = datetime.now(UTC)


def read_attempt(receipt_id):
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        return (
            receipt.processing_status,
            receipt.processing_version,
            receipt.automatic_ocr_retries,
        )


def test_redis_outage_preserves_dispatch_request(receipt_id, monkeypatch):
    def fail(*args, **kwargs):
        raise RedisConnectionError("redis unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(receipt_dispatcher, "enqueue_receipt", fail)
        assert receipt_dispatcher.advance_due_receipt()
        assert not receipt_dispatcher.advance_due_receipt()

    assert read_attempt(receipt_id) == (ProcessingStatus.PENDING_DISPATCH, 1, 0)
    make_due(receipt_id)
    assert receipt_dispatcher.advance_due_receipt()
    assert read_attempt(receipt_id) == (ProcessingStatus.QUEUED, 1, 0)
    assert dispatch_queue.job_ids == [receipt_job_id(receipt_id, 1)]


def test_upload_stays_durable_when_dispatch_cannot_reach_redis(client, monkeypatch):
    with SessionLocal.begin() as session:
        owner = User(
            user_name="Upload",
            user_surname="Recovery",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        session.add(owner)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: owner)
    storage = Mock()
    monkeypatch.setitem(app.dependency_overrides, get_object_storage, lambda: storage)

    def offline(*args, **kwargs):
        raise RedisConnectionError("dispatch unavailable")

    image = BytesIO()
    Image.new("RGB", (128, 128)).save(image, "PNG")
    with monkeypatch.context() as patch:
        patch.setattr(receipt_dispatcher, "enqueue_receipt", offline)
        response = client.post(
            "/api/receipts/upload",
            files={"file": ("receipt.png", image.getvalue(), "image/png")},
        )
        assert response.status_code == 201, response.text
        receipt_id = response.json()["receipt_id"]
        assert response.json()["processing_status"] == "pending_dispatch"
        assert receipt_dispatcher.advance_due_receipt()
        assert (
            client.get(f"/api/receipts/{receipt_id}").json()["processing_status"]
            == "pending_dispatch"
        )
    storage.upload.assert_called_once()


def test_unconfirmed_enqueue_is_deduplicated(receipt_id):
    job_id = enqueue_receipt(receipt_id, 1, None)
    assert receipt_dispatcher.advance_due_receipt()
    assert dispatch_queue.job_ids == [job_id]
    assert read_attempt(receipt_id) == (ProcessingStatus.QUEUED, 1, 0)


def test_worker_can_claim_job_when_redis_delivery_was_not_recorded(receipt_id):
    enqueue_receipt(receipt_id, 1, None)
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id, 1)
    assert not service.start_processing(receipt_id, 1)
    assert not receipt_dispatcher.advance_due_receipt()
    assert read_attempt(receipt_id) == (ProcessingStatus.PREPROCESSING, 1, 0)


def test_missing_queued_job_is_sent_again(receipt_id):
    assert receipt_dispatcher.advance_due_receipt()
    job_id = receipt_job_id(receipt_id, 1)
    dispatch_queue.remove(job_id)
    Job.fetch(job_id, connection=queue_connection).delete()

    make_due(receipt_id)
    assert receipt_dispatcher.advance_due_receipt()
    assert read_attempt(receipt_id) == (ProcessingStatus.PENDING_DISPATCH, 1, 0)
    assert receipt_dispatcher.advance_due_receipt()
    assert dispatch_queue.job_ids == [job_id]


def test_stalled_worker_is_recovered_and_late_write_is_ignored(receipt_id):
    assert receipt_dispatcher.advance_due_receipt()
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id, 1)
    assert not receipt_dispatcher.advance_due_receipt()

    make_due(receipt_id)
    assert receipt_dispatcher.advance_due_receipt()
    assert read_attempt(receipt_id) == (ProcessingStatus.RETRY_SCHEDULED, 2, 1)
    assert (
        service.save_result(receipt_id, ReceiptProcessingResult(items=()), 1)
        == SaveProcessingOutcome.STALE_JOB
    )


@pytest.mark.parametrize(
    "delays, expected",
    [
        ((10,), ProcessingStatus.RETRY_SCHEDULED),
        ((), ProcessingStatus.FAILED),
    ],
)
def test_worker_failure_callback_respects_retry_budget(
    receipt_id, monkeypatch, delays, expected
):
    monkeypatch.setattr(setting, "receipt_retry_intervals_seconds", delays)
    assert receipt_dispatcher.advance_due_receipt()
    assert ReceiptProcessingService(SessionLocal).start_processing(receipt_id, 1)
    job = Job.fetch(receipt_job_id(receipt_id, 1), connection=queue_connection)
    retry_policy.receipt_work_horse_killed_handler(job, 123, 1, None)
    retry_policy.receipt_work_horse_killed_handler(job, 123, 1, None)
    assert read_attempt(receipt_id) == (expected, 1 + bool(delays), int(bool(delays)))
