from rq import Queue, Worker
from rq.job import Job

from backend.app.core.logging import (
    configure_logging,
    log_context,
)
from backend.app.db.session import engine
from backend.app.workers.log_context import get_job_log_context
from backend.app.workers.queue import queue_connection, receipt_queue
from backend.app.workers.retry_policy import receipt_work_horse_killed_handler


class CorrelationWorker(Worker):
    def execute_job(self, job: Job, queue: Queue) -> None:
        with log_context(**get_job_log_context(job)):
            super().execute_job(job, queue)

    def main_work_horse(self, job: Job, queue: Queue) -> None:
        engine.dispose(close=False)
        super().main_work_horse(job, queue)


def main() -> None:
    configure_logging()

    worker = CorrelationWorker(
        [receipt_queue],
        connection=queue_connection,
        maintenance_interval=30,
        worker_ttl=90,
        job_monitoring_interval=15,
        work_horse_killed_handler=receipt_work_horse_killed_handler,
    )

    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
