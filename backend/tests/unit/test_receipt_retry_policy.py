from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from backend.app.core.config import Settings, setting
from backend.app.storage.exception import ObjectStorageError
from backend.app.workers import retry_policy
from botocore.exceptions import ClientError, EndpointConnectionError
from pydantic import ValidationError
from redis.exceptions import RedisError


@pytest.mark.parametrize("intervals", [(), (10,), (10, 30, 90), (10, 10), (86400,)])
def test_valid_retry_intervals(intervals):
    config = Settings(
        _env_file=None,
        **{
            **setting.model_dump(),
            "receipt_retry_intervals_seconds": intervals,
        },
    )
    assert config.receipt_retry_intervals_seconds == intervals


@pytest.mark.parametrize("intervals", [(0,), (-1,), (30, 10), (86401,), (1,) * 6])
def test_invalid_retry_intervals(intervals):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **{
                **setting.model_dump(),
                "receipt_retry_intervals_seconds": intervals,
            },
        )


@pytest.mark.parametrize(
    "error, expected",
    [
        (TimeoutError(), True),
        (ConnectionError(), True),
        (httpx.ReadTimeout("timeout"), True),
        (httpx.ConnectError("disconnected"), True),
        (httpx.RemoteProtocolError("disconnected"), True),
        (EndpointConnectionError(endpoint_url="https://storage.test"), True),
        (ValueError("timeout"), False),
        (NotImplementedError(), False),
        (ObjectStorageError("timeout"), False),
    ],
)
def test_error_classification(error, expected):
    assert retry_policy.is_retryable_error(error) is expected


@pytest.mark.parametrize(
    "status", [400, 401, 403, 404, 408, 422, 429, 500, 502, 503, 504]
)
def test_http_error_classification(status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://ocr.test"))
    error = httpx.HTTPStatusError(
        "failure", request=response.request, response=response
    )
    assert retry_policy.is_retryable_error(error) is (
        status in {408, 429, 500, 502, 503, 504}
    )


@pytest.mark.parametrize(
    "status, code, expected",
    [
        (503, "Unknown", True),
        (400, "SlowDown", True),
        (400, "RequestTimeout", True),
        (404, "NoSuchKey", False),
        (403, "AccessDenied", False),
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_storage_error_classification(status, code, expected, wrapped):
    error = ClientError(
        {"ResponseMetadata": {"HTTPStatusCode": status}, "Error": {"Code": code}},
        "GetObject",
    )
    if wrapped:
        wrapper = ObjectStorageError("Storage failure")
        wrapper.__cause__ = error
        error = wrapper
    assert retry_policy.is_retryable_error(error) is expected


@pytest.mark.parametrize(
    "remaining, error, eligible, expected",
    [
        (3, TimeoutError(), True, 3),
        (3, TimeoutError(), False, 0),
        (3, ValueError(), True, 0),
        (0, TimeoutError(), True, 0),
        (None, TimeoutError(), True, 0),
    ],
)
def test_callback_retry_decision(monkeypatch, remaining, error, eligible, expected):
    service = Mock()
    service.can_retry_processing.return_value = eligible
    monkeypatch.setattr(
        retry_policy, "ReceiptProcessingService", Mock(return_value=service)
    )
    receipt_id = uuid4()
    job = Mock(args=(str(receipt_id), 2), retries_left=remaining)
    # RQ passes exactly these five positional arguments to a failure callback.
    retry_policy.receipt_failure_callback(job, Mock(), type(error), error, None)
    assert job.retries_left == expected
    job.save.assert_called_once_with()
    if remaining and isinstance(error, TimeoutError):
        service.can_retry_processing.assert_called_once_with(
            receipt_id=receipt_id,
            processing_version=2,
        )
    else:
        service.can_retry_processing.assert_not_called()
    if not expected:
        job.get_retry_interval.assert_not_called()


def test_callback_disables_retry_when_database_check_fails(monkeypatch):
    service = Mock()
    service.can_retry_processing.side_effect = RuntimeError("DB unavailable")
    monkeypatch.setattr(
        retry_policy, "ReceiptProcessingService", Mock(return_value=service)
    )
    job = Mock(args=(str(uuid4()), 1), retries_left=3)
    retry_policy.receipt_failure_callback(
        job, Mock(), TimeoutError, TimeoutError(), None
    )
    assert job.retries_left == 0
    job.get_retry_interval.assert_not_called()


def test_callback_keeps_local_retry_disabled_if_redis_save_fails():
    job = Mock(args=(str(uuid4()), 1), retries_left=3)
    job.save.side_effect = RedisError("Redis unavailable")
    retry_policy.receipt_failure_callback(job, Mock(), ValueError, ValueError(), None)
    assert job.retries_left == 0
