from rq import Queue, Worker
from rq.job import Job

from backend.app.core.logging import (
    configure_logging,
    log_context,
)
from backend.app.workers.log_context import get_job_log_context
from backend.app.workers.queue import queue_connection, receipt_queue


class CorrelationWorker(Worker):
    def execute_job(self, job: Job, queue: Queue) -> None:
        with log_context(**get_job_log_context(job)):
            super().execute_job(job, queue)


def main() -> None:
    configure_logging()

    worker = CorrelationWorker(
        [receipt_queue],
        connection=queue_connection,
    )

    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
