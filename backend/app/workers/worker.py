from rq import Worker

from backend.app.workers.queue import queue_connection, receipt_queue


def main() -> None:
    worker = Worker(
        [receipt_queue],
        connection=queue_connection,
    )

    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
