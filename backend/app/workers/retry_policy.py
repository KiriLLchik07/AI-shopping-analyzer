import logging
from types import TracebackType
from uuid import UUID

import httpx
from backend.app.db.session import SessionLocal
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from backend.app.storage.exception import ObjectStorageError
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from redis import Redis
from redis.exceptions import RedisError
from rq.job import Job

logger = logging.getLogger(__name__)


RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
RETRYABLE_STORAGE_CODES = {
    "SlowDown",
    "RequestTimeout",
    "RequestTimeoutException",
    "InternalError",
    "ServiceUnavailable",
}


def is_retryable_error(error: BaseException) -> bool:
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


def receipt_failure_callback(
    job: Job,
    connection: Redis,
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | None,
) -> None:
    retries_left = job.retries_left or 0

    job.retries_left = 0
    retry_allowed = False
    reason = "retry_limit_reached"

    receipt_id = None
    processing_version = None

    if retries_left > 0:
        if not is_retryable_error(exc_value):
            reason = "non_retryable_error"
        else:
            try:
                receipt_id = UUID(str(job.args[0]))
                processing_version = int(job.args[1]) if len(job.args) > 1 else 1

                service = ReceiptProcessingService(SessionLocal)
                retry_allowed = service.can_retry_processing(
                    receipt_id=receipt_id, processing_version=processing_version
                )

                reason = (
                    "temporary_error"
                    if retry_allowed
                    else "receipt_state_does_not_allow_retry"
                )
            except Exception:
                reason = "retry_state_check_failed"

                logger.exception(
                    "Could not verify receipt retry eligibility job_id=%s",
                    job.id,
                )

    if retry_allowed:
        job.retries_left = retries_left

        logger.info(
            "Receipt retry permitted "
            "receipt_id=%s processing_version=%s job_id=%s "
            "delay_seconds=%s retries_left=%s error_type=%s",
            receipt_id,
            processing_version,
            job.id,
            job.get_retry_interval(),
            retries_left,
            exc_type.__name__,
        )

    else:
        logger.info(
            "Receipt retry disabled job_id=%s reason=%s error_type=%s",
            job.id,
            reason,
            exc_type.__name__,
        )

    try:
        job.save()
    except RedisError:
        logger.exception(
            "Could not persist receipt retry policy job_id=%s",
            job.id,
        )
