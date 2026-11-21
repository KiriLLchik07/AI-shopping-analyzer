import logging
from traceback import StackSummary
from types import TracebackType
from uuid import UUID

import httpx
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from redis import Redis
from rq.exceptions import AbandonedJobError
from rq.job import Job
from sqlalchemy.exc import OperationalError

from backend.app.core.logging import log_context
from backend.app.db.session import SessionLocal
from backend.app.schemas.processing_metrics import MetricOutcome, ProcessingStage
from backend.app.services.processing_metrics_service import processing_metrics
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from backend.app.storage.exception import ObjectStorageError
from backend.app.workers.log_context import get_job_log_context

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}

RETRYABLE_STORAGE_CODES = {
    "SlowDown",
    "RequestTimeout",
    "RequestTimeoutException",
    "InternalError",
    "ServiceUnavailable",
}


class WorkHorseInterruptedError(RuntimeError):
    pass


def is_interruption_error(error: BaseException) -> bool:
    return isinstance(error, (AbandonedJobError, WorkHorseInterruptedError))


def is_retryable_error(error: BaseException) -> bool:
    if is_interruption_error(error):
        return True
    if isinstance(error, OperationalError):
        sqlstate = getattr(error.orig, "sqlstate", None) or ""
        return (
            error.connection_invalidated
            or sqlstate.startswith("08")
            or sqlstate in {"57P01", "57P02", "57P03"}
        )

    if isinstance(error, ObjectStorageError):
        cause = error.__cause__

        if cause is None:
            return False

        error = cause

    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            EndpointConnectionError,
            ConnectTimeoutError,
            ReadTimeoutError,
            ConnectionClosedError,
        ),
    ):
        return True

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_HTTP_STATUSES

    if isinstance(error, ClientError):
        response = error.response

        status = response.get(
            "ResponseMetadata",
            {},
        ).get("HTTPStatusCode")

        code = response.get(
            "Error",
            {},
        ).get("Code")

        return status in RETRYABLE_HTTP_STATUSES or code in RETRYABLE_STORAGE_CODES

    return False


def get_receipt_job_arguments(job: Job) -> tuple[UUID, int]:
    receipt_id = UUID(str(job.args[0]))
    processing_version = int(job.args[1]) if len(job.args) > 1 else 1
    return receipt_id, processing_version


def receipt_failure_callback(
    job: Job,
    connection: Redis,
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | StackSummary | None,
) -> None:
    with log_context(**get_job_log_context(job)):
        receipt_id, version = get_receipt_job_arguments(job)
        changed = ReceiptProcessingService(SessionLocal).mark_failed(
            receipt_id, exc_value, version, retryable=is_retryable_error(exc_value)
        )
        if changed and is_interruption_error(exc_value):
            processing_metrics.record(
                ProcessingStage.PIPELINE, MetricOutcome.INTERRUPTED
            )


def receipt_work_horse_killed_handler(
    job: Job, retpid: int, ret_val: int, rusage: object
) -> None:
    with log_context(**get_job_log_context(job)):
        logger.error(
            "Receipt work horse terminated unexpectedly pid=%s wait_status=%s",
            retpid,
            ret_val,
        )
        error = WorkHorseInterruptedError("Receipt work horse terminated unexpectedly")
        receipt_failure_callback(job, job.connection, type(error), error, None)
