from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rq import SimpleWorker
from rq.job import Job, JobStatus
from rq.scheduler import RQScheduler
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import select

from backend.app.core.config import setting
from backend.app.db.session import SessionLocal
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.services.receipt_processing_service import ReceiptProcessingService
from backend.app.workers import jobs
from backend.app.workers.queue import enqueue_receipt, queue_connection, receipt_queue

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


def release_scheduled(job):
    registry = receipt_queue.scheduled_job_registry
    scheduler = RQScheduler([receipt_queue], connection=queue_connection)
    scheduler.acquire_locks()
    try:
        scheduler.enqueue_scheduled_jobs()
        assert receipt_queue.count == 0  # Backoff has not elapsed yet.
        assert job.id in registry.get_job_ids()
        # Move only the test job's due date into the past; never sleep for backoff.
        queue_connection.zadd(registry.key, {job.id: 0})
        scheduler.enqueue_scheduled_jobs()
        assert receipt_queue.job_ids == [job.id]
        assert job.id not in registry.get_job_ids()
    finally:
        scheduler.release_locks()


def test_backoff_and_retry_limit(receipt_id, pipeline):
    job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    assert job.args == (str(receipt_id), 1)
    assert job.retries_left == 3
    assert job.retry_intervals == [10, 30, 90]
    for attempt, delay in enumerate((10, 30, 90), start=1):
        before = datetime.now(UTC).timestamp()
        run_queue()
        after = datetime.now(UTC).timestamp()
        job.refresh()
        assert job.get_status() == JobStatus.SCHEDULED
        assert job.retries_left == 3 - attempt
        due = receipt_queue.scheduled_job_registry.get_scheduled_time(job).timestamp()
        assert before + delay - 1 <= due <= after + delay + 1
        with SessionLocal() as session:
            receipt = session.get(Receipt, receipt_id)
            assert receipt.status == ReceiptStatus.FAILED
            assert receipt.processing_error_message
            assert "private provider error" not in receipt.processing_error_message
        release_scheduled(job)
    run_queue()
    job.refresh()
    assert pipeline.calls == 4
    assert job.retries_left == 0
    assert job.get_status() == JobStatus.FAILED
    assert receipt_queue.count == 0
    assert receipt_queue.scheduled_job_registry.count == 0
    assert job.id in receipt_queue.failed_job_registry.get_job_ids()


def test_retry_recovers_and_saves_items_once(receipt_id, pipeline):
    pipeline.failures = 1
    job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    run_queue()
    assert job.get_status() == JobStatus.SCHEDULED
    release_scheduled(job)
    run_queue()
    assert job.get_status() == JobStatus.FINISHED
    enqueue_receipt(receipt_id)
    run_queue()
    assert pipeline.calls == 2
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_message is None
        assert receipt.processing_error_code is None
        assert (
            len(
                session.scalars(
                    select(ReceiptItem).where(
                        ReceiptItem.receipt_id == receipt_id,
                    )
                ).all()
            )
            == 1
        )
    assert receipt_queue.scheduled_job_registry.count == 0


@pytest.mark.parametrize("error", [ValueError("invalid"), NotImplementedError()])
def test_permanent_error_never_retries(receipt_id, pipeline, error):
    pipeline.error = error
    job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    run_queue()
    job.refresh()
    assert job.get_status() == JobStatus.FAILED
    assert job.retries_left == 0
    assert pipeline.calls == 1
    assert receipt_queue.scheduled_job_registry.count == 0


def test_empty_intervals_disable_retries(receipt_id, pipeline, monkeypatch):
    monkeypatch.setattr(setting, "receipt_retry_intervals_seconds", ())
    job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    run_queue()
    assert job.get_status() == JobStatus.FAILED
    assert pipeline.calls == 1
    assert receipt_queue.scheduled_job_registry.count == 0


@pytest.mark.parametrize("change", ["delete", "new_version"])
def test_scheduled_retry_skips_obsolete_receipt(receipt_id, pipeline, change):
    job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    run_queue()
    assert job.get_status() == JobStatus.SCHEDULED
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        if change == "delete":
            session.delete(receipt)
        else:
            receipt.processing_version += 1
            receipt.status = ReceiptStatus.UPLOADED
    release_scheduled(job)
    run_queue()
    assert job.get_status() == JobStatus.FINISHED
    assert pipeline.calls == 1
    assert receipt_queue.scheduled_job_registry.count == 0
    if change == "new_version":
        with SessionLocal() as session:
            assert session.get(Receipt, receipt_id).status == ReceiptStatus.UPLOADED


@pytest.mark.parametrize(
    "state, expected",
    [
        (ReceiptStatus.UPLOADED, True),
        (ReceiptStatus.FAILED, True),
        (ReceiptStatus.PREPROCESSING, False),
        (ReceiptStatus.OCR_PROCESSING, False),
        (ReceiptStatus.PARSING, False),
        (ReceiptStatus.NEED_REVIEW, False),
        (ReceiptStatus.COMPLETED, False),
    ],
)
def test_retry_eligibility_by_status(receipt_id, state, expected):
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = state
    assert (
        ReceiptProcessingService(SessionLocal).can_retry_processing(receipt_id, 1)
        is expected
    )


@pytest.mark.parametrize("change", ["delete", "new_version", "saved_result"])
def test_retry_eligibility_rejects_obsolete_work(receipt_id, change):
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        if change == "delete":
            session.delete(receipt)
        elif change == "new_version":
            receipt.processing_version += 1
        else:
            receipt.processing_result_saved_at = datetime.now(UTC)
    assert not ReceiptProcessingService(SessionLocal).can_retry_processing(
        receipt_id, 1
    )
