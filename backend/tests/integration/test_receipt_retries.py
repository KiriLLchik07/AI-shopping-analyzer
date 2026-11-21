from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import select

from backend.app.core.config import setting
from backend.app.db.session import SessionLocal
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ProcessingStatus, ReceiptReviewStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.workers import jobs
from backend.app.workers.queue import queue_connection, receipt_queue
from backend.app.workers.receipt_dispatcher import advance_due_receipt

pytestmark = pytest.mark.integration


@pytest.fixture
def receipt_id():
    with SessionLocal.begin() as session:
        receipt = Receipt(
            user=User(
                user_name="Retry",
                user_surname="Test",
                user_mail=f"{uuid4()}@example.com",
                user_password_hash="test-hash",
            ),
            image_object_key="receipts/retry-test.jpg",
        )
        session.add(receipt)
        session.flush()
        return receipt.receipt_id


@pytest.fixture
def pipeline(monkeypatch):
    class Pipeline(ReceiptPipeline):
        calls = 0
        failures = 99
        error = TimeoutError("private provider error")

        def preprocess(self, source):
            self.calls += 1
            if self.calls <= self.failures:
                raise self.error
            return b"image"

        def recognize(self, image):
            return "Milk"

        def parse(self, raw_text):
            return ReceiptProcessingResult(
                items=(ReceiptItemCreateRequest(raw_name="Milk", quantity=1),)
            )

    instance = Pipeline()
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: instance)
    monkeypatch.setattr(setting, "receipt_retry_intervals_seconds", (10, 30, 90))
    return instance


def run_queue():
    # Same-process worker keeps the pipeline stub visible on Windows. RQ still
    # performs real queue, callback, registry and retry operations against Redis.
    worker = SimpleWorker([receipt_queue], connection=queue_connection)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(burst=True, with_scheduler=False, logging_level="CRITICAL")


def release_scheduled(receipt_id):
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.processing_status == ProcessingStatus.RETRY_SCHEDULED
        assert receipt.ocr_due_at > datetime.now(UTC)
        receipt.ocr_due_at = datetime.now(UTC)


def test_backoff_and_retry_limit(receipt_id, pipeline):
    for attempt in range(4):
        if attempt:
            assert not advance_due_receipt()
            release_scheduled(receipt_id)
        assert advance_due_receipt()
        run_queue()
        with SessionLocal() as session:
            receipt = session.get(Receipt, receipt_id)
            assert receipt.automatic_ocr_retries == min(attempt + 1, 3)
            assert receipt.processing_status == (
                ProcessingStatus.RETRY_SCHEDULED
                if attempt < 3
                else ProcessingStatus.FAILED
            )
    assert pipeline.calls == 4
    assert not advance_due_receipt()


def test_retry_recovers_and_saves_items_once(receipt_id, pipeline):
    pipeline.failures = 1
    assert advance_due_receipt()
    run_queue()
    release_scheduled(receipt_id)
    assert advance_due_receipt()
    run_queue()
    jobs.process_receipt(str(receipt_id), 1)
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.receipt_status == ReceiptReviewStatus.NEEDS_REVIEW
        assert receipt.processing_status == ProcessingStatus.SUCCEEDED
        assert (
            len(
                session.scalars(
                    select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
                ).all()
            )
            == 1
        )
    assert pipeline.calls == 2


def test_permanent_failure_does_not_retry(receipt_id, pipeline):
    pipeline.error = ValueError("provider detail")
    assert advance_due_receipt()
    run_queue()
    assert not advance_due_receipt()
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.processing_status == ProcessingStatus.FAILED
        assert receipt.automatic_ocr_retries == 0
        assert "provider detail" not in receipt.processing_error_message


def test_manual_run_keeps_spent_automatic_budget(receipt_id, pipeline):
    from backend.app.services.receipt_processing_service import ReceiptProcessingService

    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        owner = receipt.receipt_user_id
        receipt.processing_status = ProcessingStatus.FAILED
        receipt.automatic_ocr_retries = 3
        receipt.ocr_due_at = None

    ReceiptProcessingService(SessionLocal).prepare_process(receipt_id, owner, False)
    assert advance_due_receipt()
    run_queue()
    assert not advance_due_receipt()
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.processing_status == ProcessingStatus.FAILED
        assert receipt.manual_ocr_runs == 1
        assert receipt.automatic_ocr_retries == 3
