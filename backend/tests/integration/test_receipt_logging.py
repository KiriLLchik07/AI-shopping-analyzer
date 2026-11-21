import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from rq import SimpleWorker
from rq.job import Job, JobStatus
from rq.timeouts import TimerDeathPenalty

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.config import setting
from backend.app.core.logging import LogContextFilter, get_correlation_id, log_context
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, User
from backend.app.models.enums import ProcessingStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.workers import jobs
from backend.app.workers.queue import (
    dispatch_queue,
    enqueue_receipt,
    queue_connection,
    receipt_job_id,
    receipt_queue,
)
from backend.app.workers.receipt_dispatcher import advance_due_receipt

pytestmark = pytest.mark.integration


@pytest.fixture
def owner_client():
    with SessionLocal.begin() as session:
        user = User(
            user_name="Logging",
            user_surname="Test",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test",
        )
        receipt = Receipt(
            user=user,
            image_object_key="receipts/logging.jpg",
            processing_status=ProcessingStatus.FAILED,
            ocr_due_at=None,
        )
        session.add(receipt)
        session.flush()
        receipt_id = receipt.receipt_id
        session.expunge(user)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            yield client, receipt_id
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def logs(caplog):
    context_filter = LogContextFilter()
    caplog.handler.addFilter(context_filter)
    with caplog.at_level(logging.INFO):
        yield caplog
    caplog.handler.removeFilter(context_filter)


def run_queue():
    worker = SimpleWorker([receipt_queue], connection=queue_connection)
    worker.death_penalty_class = TimerDeathPenalty
    worker.work(burst=True, with_scheduler=False, logging_level="CRITICAL")
    assert get_correlation_id() is None


@pytest.mark.parametrize("failure", [None, TimeoutError, ValueError])
def test_http_queue_pipeline_and_callback_share_ids(
    owner_client, monkeypatch, logs, failure
):
    client, receipt_id = owner_client
    calls = []

    class Pipeline(ReceiptPipeline):
        def preprocess(self, source):
            calls.append(get_correlation_id())
            logging.getLogger("test.pipeline").info("Pipeline internal event")
            if failure is not None and len(calls) == 1:
                raise failure("provider detail")
            return b"image"

        def recognize(self, image):
            return "Milk"

        def parse(self, raw_text):
            return ReceiptProcessingResult(
                items=(ReceiptItemCreateRequest(raw_name="Milk", quantity=1),)
            )

    monkeypatch.setattr(jobs, "get_receipt_pipeline", Pipeline)
    monkeypatch.setattr(setting, "receipt_retry_intervals_seconds", (10, 30, 90))
    cid = str(uuid4())
    response = client.post(
        f"/api/receipts/{receipt_id}/reprocess", headers={"X-Correlation-ID": cid}
    )
    assert response.status_code == 202
    assert response.headers["X-Correlation-ID"] == cid
    job_id = response.json()["job_id"]
    version = response.json()["processing_version"]
    assert advance_due_receipt()
    job = Job.fetch(job_id, connection=queue_connection)
    assert job.meta["correlation_id"] == cid
    assert job.args == (str(receipt_id), version)
    assert job.kwargs == {}
    run_queue()
    if failure is TimeoutError:
        assert job.get_status() == JobStatus.FAILED
        with SessionLocal.begin() as session:
            receipt = session.get(Receipt, receipt_id)
            assert receipt.processing_status == ProcessingStatus.RETRY_SCHEDULED
            receipt.ocr_due_at = datetime.now(UTC)
        assert advance_due_receipt()
        next_job = Job.fetch(
            receipt_job_id(receipt_id, version + 1), connection=queue_connection
        )
        assert next_job.meta["correlation_id"] == cid
        run_queue()
        assert next_job.get_status() == JobStatus.FINISHED
        assert calls == [cid, cid]
    else:
        assert calls == [cid]
        assert job.get_status() == (
            JobStatus.FAILED if failure is ValueError else JobStatus.FINISHED
        )
    events = [
        entry
        for entry in logs.records
        if entry.name
        in {"backend.app.workers.jobs", "backend.app.workers.queue", "test.pipeline"}
    ]
    for entry in events:
        assert entry.correlation_id == cid
        assert entry.receipt_id == str(receipt_id)
        assert entry.processing_version in {version, version + 1}
        assert entry.job_id == receipt_job_id(receipt_id, entry.processing_version)
    messages = [entry.getMessage() for entry in events]
    assert "Receipt enqueued" in messages
    assert "Pipeline internal event" in messages
    if failure:
        assert "Receipt processing failed" in messages


def test_enqueue_error_logs_generated_job_id_and_restores_context(monkeypatch, logs):
    def fail(*args, **kwargs):
        raise RedisError("unavailable")

    monkeypatch.setattr(dispatch_queue, "enqueue", fail)
    cid, receipt_id = str(uuid4()), uuid4()
    with log_context(correlation_id=cid):
        with pytest.raises(RedisError):
            enqueue_receipt(receipt_id, 4, cid)
        assert get_correlation_id() == cid
        logging.getLogger("test.after_enqueue").info("After enqueue")
    entries = [
        entry for entry in logs.records if entry.name == "backend.app.workers.queue"
    ]
    assert len(entries) == 2
    assert entries[0].job_id == entries[1].job_id != "-"
    assert entries[1].exc_info
    assert all(
        entry.correlation_id == cid and entry.receipt_id == str(receipt_id)
        for entry in entries
    )
    after = next(entry for entry in logs.records if entry.name == "test.after_enqueue")
    assert after.job_id == "-"
    assert get_correlation_id() is None


def test_sequential_jobs_do_not_share_context(logs):
    expected = {}
    for _ in range(2):
        cid, receipt_id = str(uuid4()), uuid4()
        with log_context(correlation_id=cid):
            job_id = enqueue_receipt(receipt_id, 1, cid)
        expected[job_id] = (cid, str(receipt_id))
    # Missing receipts exercise the early-return path in the same worker.
    run_queue()
    entries = [
        entry
        for entry in logs.records
        if entry.name == "backend.app.workers.jobs"
        and entry.getMessage().startswith("Receipt job skipped")
    ]
    assert len(entries) == 2
    assert {entry.job_id for entry in entries} == set(expected)
    for entry in entries:
        assert (entry.correlation_id, entry.receipt_id) == expected[entry.job_id]
    assert get_correlation_id() is None
