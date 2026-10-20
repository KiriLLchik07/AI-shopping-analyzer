from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from redis import Redis
from redis.exceptions import RedisError

from backend.app.core.config import metrics_settings, setting
from backend.app.db.session import SessionLocal
from backend.app.models import Receipt, User
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.processing_metrics_repository import (
    ProcessingMetricsRepository,
)
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.processing_metrics import MetricOutcome, ProcessingStage
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.processing_metrics_service import (
    ProcessingMetricsService,
    processing_metrics,
)
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.services.receipt_processing_service import ReceiptProcessingService
from backend.app.workers import jobs, retry_policy
from backend.app.workers.queue import queue_connection

pytestmark = pytest.mark.integration


@pytest.fixture
def metrics_receipt():
    with SessionLocal.begin() as session:
        user = User(
            user_name="Metrics",
            user_surname="Test",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test",
        )
        receipt = Receipt(user=user, image_object_key="metrics/test.jpg")
        session.add(receipt)
        session.flush()
        return receipt.receipt_id


class Pipeline(ReceiptPipeline):
    def preprocess(self, source):
        return b"image"

    def recognize(self, image):
        return "Milk"

    def parse(self, raw_text):
        return ReceiptProcessingResult(
            items=(ReceiptItemCreateRequest(raw_name="Milk", quantity=1),)
        )


def snapshot():
    return processing_metrics.snapshot(datetime.now(UTC).date()).stages


def test_success_skips_and_stale_jobs_have_distinct_outcomes(
    metrics_receipt, monkeypatch
):
    monkeypatch.setattr(jobs, "get_receipt_pipeline", Pipeline)
    jobs.process_receipt(str(metrics_receipt))
    jobs.process_receipt(str(metrics_receipt))
    jobs.process_receipt(str(metrics_receipt), 99)
    data = snapshot()
    assert data[ProcessingStage.PIPELINE].success == 1
    assert data[ProcessingStage.PIPELINE].skipped == 2
    assert data[ProcessingStage.PIPELINE].error_rate == 0
    assert data[ProcessingStage.PIPELINE].duration_samples == 1
    assert data[ProcessingStage.OCR].success == 1
    assert data[ProcessingStage.OCR].mean_seconds is not None
    assert data[ProcessingStage.CLAIM].skipped == 2


@pytest.mark.parametrize(
    "stage", [s for s in ProcessingStage if s != ProcessingStage.PIPELINE]
)
def test_errors_are_attributed_to_the_actual_stage(metrics_receipt, monkeypatch, stage):
    pipeline = Pipeline()
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline)

    def fail(*args, **kwargs):
        raise ValueError("original stage failure")

    targets = {
        ProcessingStage.CLAIM: (ReceiptProcessingService, "start_processing"),
        ProcessingStage.SETUP: (jobs, "get_receipt_pipeline"),
        ProcessingStage.PREPROCESSING: (pipeline, "preprocess"),
        ProcessingStage.PERSIST_PREPROCESSING: (
            ReceiptProcessingService,
            "advance_status",
        ),
        ProcessingStage.OCR: (pipeline, "recognize"),
        ProcessingStage.PERSIST_OCR: (ReceiptProcessingService, "save_ocr_result"),
        ProcessingStage.PARSING: (pipeline, "parse"),
        ProcessingStage.SAVING: (ReceiptProcessingService, "save_result"),
    }
    target, method = targets[stage]
    monkeypatch.setattr(target, method, fail)
    with pytest.raises(ValueError, match="original stage failure"):
        jobs.process_receipt(str(metrics_receipt))
    data = snapshot()
    assert data[ProcessingStage.PIPELINE].error == 1
    assert data[ProcessingStage.PIPELINE].error_rate == 1
    assert data[stage].error == 1
    assert data[stage].duration_samples == 1
    if stage in {
        ProcessingStage.PERSIST_OCR,
        ProcessingStage.PARSING,
        ProcessingStage.SAVING,
    }:
        assert data[ProcessingStage.OCR].success == 1
        assert data[ProcessingStage.OCR].error_rate == 0


def test_state_change_after_ocr_stops_pipeline_without_counting_failure(
    metrics_receipt, monkeypatch
):
    pipeline = Pipeline()
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline)
    monkeypatch.setattr(
        ReceiptProcessingService, "save_ocr_result", lambda *a, **k: False
    )
    jobs.process_receipt(str(metrics_receipt))
    data = snapshot()
    assert data[ProcessingStage.PIPELINE].stopped == 1
    assert data[ProcessingStage.PIPELINE].error_rate is None
    assert data[ProcessingStage.OCR].success == 1
    assert data[ProcessingStage.PARSING].attempts == 0


def test_retry_counts_attempts_instead_of_unique_receipts(metrics_receipt, monkeypatch):
    pipeline = Pipeline()
    recognize = Mock(side_effect=[TimeoutError("temporary"), "Milk"])
    monkeypatch.setattr(pipeline, "recognize", recognize)
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline)
    with pytest.raises(TimeoutError):
        jobs.process_receipt(str(metrics_receipt))
    jobs.process_receipt(str(metrics_receipt))
    for stage in (ProcessingStage.PIPELINE, ProcessingStage.OCR):
        data = snapshot()[stage]
        assert data.attempts == 2
        assert data.success == data.error == 1
        assert data.error_rate == 0.5


def test_atomic_counters_shared_by_independent_clients():
    day = datetime.now(UTC).date()

    def write(index):
        with Redis.from_url(setting.redis_url, decode_responses=True) as client:
            metrics = ProcessingMetricsService(ProcessingMetricsRepository(client, 30))
            outcome = MetricOutcome.SUCCESS if index % 2 == 0 else MetricOutcome.ERROR
            for _ in range(10):
                metrics.record(ProcessingStage.OCR, outcome, 2 if index % 2 == 0 else 4)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(8)))
    data = snapshot()[ProcessingStage.OCR]
    assert data.success == data.error == 40
    assert data.error_rate == 0.5
    assert data.mean_seconds == 3
    assert data.duration_samples == 80
    assert 0 < queue_connection.ttl(ProcessingMetricsRepository.key(day)) <= 30 * 86400


def test_metrics_write_failure_does_not_fail_receipt(metrics_receipt, monkeypatch):
    monkeypatch.setattr(jobs, "get_receipt_pipeline", Pipeline)
    monkeypatch.setattr(
        processing_metrics.repository, "record", Mock(side_effect=RedisError("offline"))
    )
    jobs.process_receipt(str(metrics_receipt))
    with SessionLocal() as session:
        receipt = session.get(Receipt, metrics_receipt)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None


def test_parent_reports_interruption_once_without_unknown_duration(metrics_receipt):
    with SessionLocal.begin() as session:
        session.get(Receipt, metrics_receipt).status = ReceiptStatus.OCR_PROCESSING
    job = Mock(
        id=str(uuid4()),
        args=(str(metrics_receipt), 1),
        meta={},
        retries_left=0,
        connection=queue_connection,
    )
    error = retry_policy.WorkHorseInterruptedError("work horse killed")
    for _ in range(2):
        retry_policy.receipt_failure_callback(
            job, queue_connection, type(error), error, None
        )
    data = snapshot()
    assert data[ProcessingStage.PIPELINE].interrupted == 1
    assert data[ProcessingStage.PIPELINE].error_rate == 1
    assert data[ProcessingStage.PIPELINE].duration_samples == 0
    assert data[ProcessingStage.PIPELINE].mean_seconds is None
    assert data[ProcessingStage.OCR].error == 0  # The killed stage is unknown.


def test_metrics_endpoint_is_opt_in_and_requires_token(client, monkeypatch):
    path = "/internal/processing-metrics"
    monkeypatch.setattr(metrics_settings, "access_token", None)
    assert client.get(path).status_code == 404
    monkeypatch.setattr(
        metrics_settings, "access_token", SecretStr("metrics-test-token")
    )
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    response = client.get(path, headers={"Authorization": "Bearer metrics-test-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "UTC"
    assert body["stages"]["ocr"]["error_rate"] is None
    assert (
        "receipt_id" not in response.text and "metrics-test-token" not in response.text
    )
    assert (
        client.get(
            path + "?day=not-a-date",
            headers={"Authorization": "Bearer metrics-test-token"},
        ).status_code
        == 422
    )


def test_metrics_endpoint_hides_redis_errors(client, monkeypatch):
    monkeypatch.setattr(
        metrics_settings, "access_token", SecretStr("metrics-test-token")
    )
    monkeypatch.setattr(
        processing_metrics.repository,
        "read",
        Mock(side_effect=RedisError("SECRET internal host")),
    )
    response = client.get(
        "/internal/processing-metrics",
        headers={"Authorization": "Bearer metrics-test-token"},
    )
    assert response.status_code == 503
    assert "SECRET" not in response.text


def test_endpoint_returns_counts_and_durations_for_selected_utc_day(
    client, monkeypatch
):
    monkeypatch.setattr(
        metrics_settings, "access_token", SecretStr("metrics-test-token")
    )
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    repository = processing_metrics.repository
    repository.record(today, ProcessingStage.OCR, MetricOutcome.SUCCESS, 2)
    repository.record(today, ProcessingStage.OCR, MetricOutcome.ERROR, 4)
    repository.record(yesterday, ProcessingStage.OCR, MetricOutcome.SUCCESS, 7)
    headers = {"Authorization": "Bearer metrics-test-token"}
    for day, attempts, rate, duration in ((today, 2, 0.5, 3), (yesterday, 1, 0, 7)):
        response = client.get(
            f"/internal/processing-metrics?day={day.isoformat()}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["day"] == day.isoformat()
        row = response.json()["stages"]["ocr"]
        assert row["attempts"] == row["duration_samples"] == attempts
        assert row["error_rate"] == rate
        assert row["mean_seconds"] == duration
