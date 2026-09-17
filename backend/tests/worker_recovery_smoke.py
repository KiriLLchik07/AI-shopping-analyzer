import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

from rq.job import Job, JobStatus
from sqlalchemy import select

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.workers import jobs
from backend.app.workers.queue import enqueue_receipt, queue_connection, receipt_queue
from backend.app.workers.retry_policy import receipt_work_horse_killed_handler
from backend.app.workers.worker import CorrelationWorker


class SmokePipeline(ReceiptPipeline):
    def preprocess(self, source):
        if os.environ["RECOVERY_SMOKE_MODE"] == "block":
            queue_connection.set(
                os.environ["RECOVERY_SMOKE_READY"], os.getpid(), ex=120
            )
            time.sleep(120)
        return b"image"

    def recognize(self, image):
        return "Milk"

    def parse(self, raw_text):
        return ReceiptProcessingResult(
            items=(ReceiptItemCreateRequest(raw_name="Milk", quantity=1),)
        )


def check_environment():
    if sys.platform != "linux":
        raise RuntimeError("This test requires Linux and fork()")
    if engine.url.database != "ai_shopping_test" or engine.url.host != "postgres-test":
        raise RuntimeError("Only the isolated Compose test database is allowed")
    config = queue_connection.connection_pool.connection_kwargs
    if config.get("host") != "redis-test" or config.get("db") != 15:
        raise RuntimeError("Only the isolated Compose test Redis DB 15 is allowed")


def child_worker():
    jobs.get_receipt_pipeline = SmokePipeline
    worker = CorrelationWorker(
        [receipt_queue],
        connection=queue_connection,
        work_horse_killed_handler=receipt_work_horse_killed_handler,
        maintenance_interval=30,
        worker_ttl=90,
        job_monitoring_interval=15,
    )
    worker.work(burst=True, with_scheduler=True, logging_level="WARNING")


def run_scenario(kill_parent):
    processes = []
    ready_key = f"recovery-smoke:{uuid4()}"
    job = None
    with SessionLocal.begin() as session:
        user = User(
            user_name="Smoke",
            user_surname="Test",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test",
        )
        receipt = Receipt(user=user, image_object_key="smoke.jpg")
        session.add(receipt)
        session.flush()
        receipt_id, user_id = receipt.receipt_id, user.user_id

    def spawn(mode):
        env = {
            **os.environ,
            "RECOVERY_SMOKE_MODE": mode,
            "RECOVERY_SMOKE_READY": ready_key,
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.tests.worker_recovery_smoke", "worker"],
            env=env,
            start_new_session=True,
        )
        processes.append(process)
        return process

    try:
        job = Job.fetch(enqueue_receipt(receipt_id), connection=queue_connection)
        cid = job.meta["correlation_id"]
        first = spawn("block")
        deadline = time.monotonic() + 30
        while not (horse_pid := queue_connection.get(ready_key)):
            if first.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Worker did not start the pipeline")
            time.sleep(0.1)

        if kill_parent:
            os.killpg(first.pid, signal.SIGKILL)
            first.wait(timeout=10)
            # Accelerate only this crashed execution's expiry. Cleanup itself
            # is performed by a newly started real CorrelationWorker.
            registry = receipt_queue.started_job_registry
            for job_id, execution_id in registry.get_job_and_execution_ids(
                cleanup=False
            ):
                if job_id == job.id:
                    queue_connection.zadd(registry.key, {f"{job_id}:{execution_id}": 0})
            assert spawn("success").wait(timeout=30) == 0
        else:
            os.kill(int(horse_pid), signal.SIGKILL)
            assert first.wait(timeout=30) == 0

        job.refresh()
        assert job.get_status() == JobStatus.SCHEDULED
        assert job.retries_left == 2
        with SessionLocal() as session:
            receipt = session.get(Receipt, receipt_id)
            assert receipt.status == ReceiptStatus.FAILED
            assert receipt.processing_error_code == "processing_interrupted"

        # Avoid waiting for backoff while still using RQ's real scheduler.
        queue_connection.zadd(receipt_queue.scheduled_job_registry.key, {job.id: 0})
        assert spawn("success").wait(timeout=30) == 0
        job.refresh()
        assert job.get_status() == JobStatus.FINISHED
        assert job.meta["correlation_id"] == cid
        assert job.retries_left == 2
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
        print(
            f"PASS: {'worker process group' if kill_parent else 'work horse'} killed and recovered",
            flush=True,
        )
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        queue_connection.delete(ready_key)
        if job is not None:
            job.delete()
        with SessionLocal.begin() as session:
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)


if __name__ == "__main__":
    check_environment()
    if sys.argv[1:] == ["worker"]:
        child_worker()
    else:
        Base.metadata.create_all(engine)
        run_scenario(kill_parent=True)
        run_scenario(kill_parent=False)
