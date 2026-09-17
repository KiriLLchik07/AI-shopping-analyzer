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
from redis.exceptions import RedisError
from rq.exceptions import AbandonedJobError
from rq.job import Job

from backend.app.core.logging import log_context
from backend.app.db.session import SessionLocal
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


def restore_interrupted_receipt(job: Job) -> None:
    receipt_id, processing_version = get_receipt_job_arguments(job)
    service = ReceiptProcessingService(SessionLocal)
    try:
        changed = service.mark_interrupted(
            receipt_id=receipt_id, processing_version=processing_version
        )
    except Exception:
        logger.exception("Could not persist interrupted receipt state")
        raise
    logger.info("Receipt interruption handled state_changed=%s", changed)


def receipt_failure_callback(
    job: Job,
    connection: Redis,
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | StackSummary | None,
) -> None:
    with log_context(**get_job_log_context(job)):
        if is_interruption_error(exc_value):
            restore_interrupted_receipt(job)

        _apply_retry_policy(
            job=job,
            exc_type=exc_type,
            exc_value=exc_value,
        )


def _apply_retry_policy(
    job: Job,
    exc_type: type[BaseException],
    exc_value: BaseException,
) -> None:
    retries_left = job.retries_left or 0

    job.retries_left = 0
    retry_allowed = False
    reason = "retry_limit_reached"

    if retries_left > 0:
        if not is_retryable_error(exc_value):
            reason = "non_retryable_error"
        else:
            try:
                receipt_id, processing_version = get_receipt_job_arguments(job)

                service = ReceiptProcessingService(SessionLocal)

                retry_allowed = service.can_retry_processing(
                    receipt_id=receipt_id,
                    processing_version=processing_version,
                )

                reason = (
                    "temporary_error"
                    if retry_allowed
                    else "receipt_state_does_not_allow_retry"
                )

            except Exception:
                reason = "retry_state_check_failed"

                logger.exception("Could not verify receipt retry eligibility")

    if retry_allowed:
        job.retries_left = retries_left

        logger.info(
            "Receipt retry permitted delay_seconds=%s retries_left=%s error_type=%s",
            job.get_retry_interval(),
            retries_left,
            exc_type.__name__,
        )
    else:
        logger.info(
            "Receipt retry disabled reason=%s error_type=%s",
            reason,
            exc_type.__name__,
        )

    try:
        job.save()
    except RedisError:
        logger.exception("Could not persist receipt retry policy")


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
