from unittest.mock import Mock

import pytest
from rq import Worker
from rq.exceptions import AbandonedJobError

from backend.app.workers import worker
from backend.app.workers.retry_policy import (
    WorkHorseInterruptedError,
    is_retryable_error,
    receipt_work_horse_killed_handler,
)


@pytest.mark.parametrize("error", [AbandonedJobError(), WorkHorseInterruptedError()])
def test_interruptions_allow_bounded_retry(error):
    assert is_retryable_error(error)


def test_child_replaces_pool_before_running_job(monkeypatch):
    events = []

    def dispose(*, close):
        assert close is False
        events.append("dispose")

    def main_work_horse(self, job, queue):
        events.append("execute")

    monkeypatch.setattr(worker.engine, "dispose", dispose)
    monkeypatch.setattr(Worker, "main_work_horse", main_work_horse)
    instance = object.__new__(worker.CorrelationWorker)
    instance.main_work_horse(Mock(), Mock())
    assert events == ["dispose", "execute"]


def test_worker_enables_recovery_and_scheduler(monkeypatch):
    instance = Mock()
    constructor = Mock(return_value=instance)
    monkeypatch.setattr(worker, "CorrelationWorker", constructor)
    monkeypatch.setattr(worker, "configure_logging", Mock())
    worker.main()
    constructor.assert_called_once_with(
        [worker.receipt_queue],
        connection=worker.queue_connection,
        maintenance_interval=30,
        worker_ttl=90,
        job_monitoring_interval=15,
        work_horse_killed_handler=receipt_work_horse_killed_handler,
    )
    instance.work.assert_called_once_with(with_scheduler=True)
