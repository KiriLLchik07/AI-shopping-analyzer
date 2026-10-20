from datetime import date
from unittest.mock import Mock

import pytest
from redis.exceptions import RedisError

from backend.app.schemas.processing_metrics import MetricOutcome, ProcessingStage
from backend.app.services import processing_metrics_service as module


@pytest.mark.parametrize("failure", [False, True])
def test_measure_records_failed_time_and_preserves_exception(monkeypatch, failure):
    repository = Mock()
    service = module.ProcessingMetricsService(repository)
    ticks = iter([10.0, 12.75])
    monkeypatch.setattr(module, "perf_counter", lambda: next(ticks))
    original = ValueError("original")
    if failure:
        with pytest.raises(ValueError) as caught, service.measure(ProcessingStage.OCR):
            raise original
        assert caught.value is original
    else:
        with service.measure(ProcessingStage.OCR):
            pass
    _, stage, outcome, elapsed = repository.record.call_args.args
    assert stage == ProcessingStage.OCR
    assert outcome == (MetricOutcome.ERROR if failure else MetricOutcome.SUCCESS)
    assert elapsed == 2.75


def test_metrics_outage_does_not_break_success_or_replace_failure(caplog):
    repository = Mock()
    repository.record.side_effect = RedisError("unavailable")
    service = module.ProcessingMetricsService(repository)
    with service.measure(ProcessingStage.OCR):
        pass
    with (
        pytest.raises(ValueError, match="original"),
        service.measure(ProcessingStage.OCR),
    ):
        raise ValueError("original")
    assert "Could not persist processing metric" in caplog.text


def test_pipeline_system_exit_is_left_for_parent_callback():
    repository = Mock()
    service = module.ProcessingMetricsService(repository)
    with pytest.raises(SystemExit), service.measure(ProcessingStage.PIPELINE):
        raise SystemExit(1)
    repository.record.assert_not_called()


def test_snapshot_has_explicit_denominator_and_ignores_skip_durations():
    repository = Mock(retention_days=30)
    repository.read.return_value = {
        "pipeline:success:count": "2",
        "pipeline:error:count": "1",
        "pipeline:interrupted:count": "1",
        "pipeline:skipped:count": "9",
        "pipeline:stopped:count": "2",
        "pipeline:success:duration_count": "2",
        "pipeline:success:duration_us": "6000000",
        "pipeline:error:duration_count": "1",
        "pipeline:error:duration_us": "9000000",
        "pipeline:skipped:duration_count": "9",
        "pipeline:skipped:duration_us": "9000",
    }
    snapshot = module.ProcessingMetricsService(repository).snapshot(date(2026, 10, 20))
    metrics = snapshot.stages[ProcessingStage.PIPELINE]
    assert metrics.attempts == 15
    assert metrics.error_rate == 0.5
    assert metrics.duration_samples == 3
    assert metrics.mean_seconds == 5
    assert metrics.mean_success_seconds == 3
    assert metrics.mean_error_seconds == 9
    assert snapshot.stages[ProcessingStage.OCR].error_rate is None
    assert snapshot.stages[ProcessingStage.OCR].mean_seconds is None


def test_empty_day_does_not_claim_zero_error_rate():
    repository = Mock(retention_days=30)
    repository.read.return_value = {}
    snapshot = module.ProcessingMetricsService(repository).snapshot(date(2026, 10, 20))
    assert all(
        row.error_rate is None and row.mean_seconds is None
        for row in snapshot.stages.values()
    )
