from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rq import SimpleWorker
from rq.executions import Execution
from rq.job import Job, JobStatus
from rq.registry import StartedJobRegistry
from rq.scheduler import RQScheduler
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.app.core.config import setting
from backend.app.core.logging import log_context
from backend.app.db.session import SessionLocal
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_processing_service import ReceiptProcessingService
from backend.app.workers import jobs, retry_policy
from backend.app.workers.queue import enqueue_receipt, queue_connection, receipt_queue

pytestmark = pytest.mark.integration


@pytest.fixture
def receipt_id(monkeypatch):
    monkeypatch.setattr(setting, "receipt_retry_intervals_seconds", (10, 30, 90))
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


def started_job(receipt_id, remaining=3):
    cid = str(uuid4())
    with log_context(correlation_id=cid):
        job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
    receipt_queue.remove(job.id)
    job.retries_left = remaining
    job.set_status(JobStatus.STARTED)
    job.save()
    with queue_connection.pipeline() as pipe:
        execution = Execution.create(
            job, ttl=300, pipeline=pipe, worker_name="dead-worker"
        )
        pipe.execute()
    registry = StartedJobRegistry(receipt_queue.name, connection=queue_connection)
    registry.death_penalty_class = TimerDeathPenalty
    return job, execution, registry


def expire(execution, registry):
    # Change only the test execution's heartbeat deadline; no wall-clock sleeps.
    queue_connection.zadd(registry.key, {execution.composite_key: 0})


def set_state(receipt_id, state):
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = state


@pytest.mark.parametrize(
    "state",
    [
        ReceiptStatus.UPLOADED,
        ReceiptStatus.PREPROCESSING,
        ReceiptStatus.OCR_PROCESSING,
        ReceiptStatus.PARSING,
    ],
)
def test_abandoned_job_restores_status_and_schedules_retry(receipt_id, state):
    set_state(receipt_id, state)
    job, execution, registry = started_job(receipt_id)
    cid = job.meta["correlation_id"]
    expire(execution, registry)
    before = datetime.now(UTC).timestamp()
    registry.cleanup()
    job.refresh()
    assert job.get_status() == JobStatus.SCHEDULED
    assert job.retries_left == 2
    assert job.meta["correlation_id"] == cid
    assert job.args == (str(receipt_id), 1)
    due = receipt_queue.scheduled_job_registry.get_scheduled_time(job).timestamp()
    assert before + 9 <= due <= datetime.now(UTC).timestamp() + 11
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.FAILED
        assert receipt.processing_error_code == "processing_interrupted"
        assert receipt.processing_error_message
    # Cleanup is idempotent and does not consume another retry.
    registry.cleanup()
    job.refresh()
    assert job.retries_left == 2


def test_unexpired_execution_is_not_recovered(receipt_id):
    set_state(receipt_id, ReceiptStatus.OCR_PROCESSING)
    job, execution, registry = started_job(receipt_id)
    registry.cleanup()
    job.refresh()
    assert job.get_status() == JobStatus.STARTED
    assert job.retries_left == 3
    assert queue_connection.zscore(registry.key, execution.composite_key) is not None
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).status == ReceiptStatus.OCR_PROCESSING


def test_exhausted_job_becomes_failed_and_can_be_reprocessed(receipt_id):
    set_state(receipt_id, ReceiptStatus.PARSING)
    job, execution, registry = started_job(receipt_id, remaining=0)
    expire(execution, registry)
    registry.cleanup()
    job.refresh()
    assert job.get_status() == JobStatus.FAILED
    assert job.retries_left == 0
    assert receipt_queue.scheduled_job_registry.count == 0
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.FAILED
        assert receipt.processing_error_code == "processing_interrupted"
        owner = receipt.receipt_user_id
    ticket = ReceiptProcessingService(SessionLocal).prepare_process(
        receipt_id, owner, False
    )
    assert ticket.processing_version == 2


@pytest.mark.parametrize("change", ["deleted", "new_version", "saved"])
def test_recovery_does_not_modify_obsolete_or_saved_receipt(receipt_id, change):
    set_state(receipt_id, ReceiptStatus.PARSING)
    job, execution, registry = started_job(receipt_id)
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        if change == "deleted":
            session.delete(receipt)
        elif change == "new_version":
            receipt.processing_version = 2
            receipt.status = ReceiptStatus.OCR_PROCESSING
        else:
            receipt.processing_result_saved_at = datetime.now(UTC)
            receipt.status = ReceiptStatus.NEED_REVIEW
            session.add(
                ReceiptItem(receipt_id=receipt_id, raw_name="Saved", quantity=1)
            )
    expire(execution, registry)
    registry.cleanup()
    job.refresh()
    assert job.retries_left == 0
    assert receipt_queue.scheduled_job_registry.count == 0
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        if change == "deleted":
            assert receipt is None
        else:
            assert receipt.processing_error_code is None
            if change == "new_version":
                assert receipt.processing_version == 2
                assert receipt.status == ReceiptStatus.OCR_PROCESSING
            else:
                assert receipt.status == ReceiptStatus.NEED_REVIEW
                assert (
                    session.scalars(
                        select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
                    )
                    .one()
                    .raw_name
                    == "Saved"
                )


def test_database_failure_keeps_abandoned_execution_recoverable(
    receipt_id, monkeypatch
):
    set_state(receipt_id, ReceiptStatus.OCR_PROCESSING)
    job, execution, registry = started_job(receipt_id)
    expire(execution, registry)

    def unavailable(*args, **kwargs):
        raise OperationalError("test", {}, RuntimeError("DB unavailable"))

    with monkeypatch.context() as patch:
        patch.setattr(ReceiptProcessingService, "mark_interrupted", unavailable)
        with pytest.raises(OperationalError):
            registry.cleanup()
    job.refresh()
    assert job.retries_left == 3
    assert job.get_status() == JobStatus.STARTED
    assert queue_connection.zscore(registry.key, execution.composite_key) is not None
    registry.cleanup()
    assert job.get_status() == JobStatus.SCHEDULED


@pytest.mark.parametrize("remaining", [0, 3])
def test_work_horse_death_uses_same_policy(receipt_id, remaining):
    set_state(receipt_id, ReceiptStatus.OCR_PROCESSING)
    job, _, _ = started_job(receipt_id, remaining=remaining)
    worker = SimpleWorker(
        [receipt_queue],
        connection=queue_connection,
        work_horse_killed_handler=retry_policy.receipt_work_horse_killed_handler,
    )
    worker.handle_work_horse_killed(job, 123, 9, None)
    assert job.retries_left == remaining
    # RQ, not our hook, owns rescheduling and decrementing the retry count.
    assert receipt_queue.scheduled_job_registry.count == 0
    worker.handle_job_failure(job, receipt_queue, exc_string="test work horse killed")
    job.refresh()
    assert job.get_status() == (JobStatus.SCHEDULED if remaining else JobStatus.FAILED)
    assert job.retries_left == max(remaining - 1, 0)
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).status == ReceiptStatus.FAILED


def test_recovered_job_finishes_without_duplicate_items(receipt_id, monkeypatch):
    set_state(receipt_id, ReceiptStatus.PARSING)
    job, execution, registry = started_job(receipt_id)
    expire(execution, registry)
    registry.cleanup()

    class Pipeline:
        def preprocess(self, source):
            return b"image"

        def recognize(self, image):
            return "Milk"

        def parse(self, raw_text):
            return ReceiptProcessingResult(
                items=(ReceiptItemCreateRequest(raw_name="Milk", quantity=1),)
            )

    monkeypatch.setattr(jobs, "get_receipt_pipeline", Pipeline)
    queue_connection.zadd(receipt_queue.scheduled_job_registry.key, {job.id: 0})
    scheduler = RQScheduler([receipt_queue], connection=queue_connection)
    scheduler.acquire_locks()
    try:
        scheduler.enqueue_scheduled_jobs()
    finally:
        scheduler.release_locks()
    worker = SimpleWorker([receipt_queue], connection=queue_connection)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(burst=True, with_scheduler=False, logging_level="CRITICAL")
    assert job.get_status() == JobStatus.FINISHED
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None
        assert (
            len(
                session.scalars(
                    select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id)
                ).all()
            )
            == 1
        )
