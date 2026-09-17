import asyncio
import io
import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from backend.app.core.logging import (
    LOG_FIELDS,
    LogContextFilter,
    configure_logging,
    get_correlation_id,
    log_context,
    normalize_correlation_id,
)
from backend.app.main import unhandled_exception_handler
from backend.app.middleware.request_logging import RequestLoggingMiddleware
from backend.app.workers.log_context import get_job_log_context
from backend.app.workers.worker import CorrelationWorker
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from rq import Worker


def record():
    result = logging.makeLogRecord({"msg": "event"})
    LogContextFilter().filter(result)
    return result


@pytest.mark.parametrize(
    "value", [None, "", "invalid", "x" * 1000, "\r\ninjected", 123]
)
def test_invalid_id_generates_uuid(value):
    result = normalize_correlation_id(value)
    assert str(UUID(result)) == result
    assert result != normalize_correlation_id(value)


def test_valid_id_is_normalized():
    expected = uuid4()
    assert normalize_correlation_id(expected.hex.upper()) == str(expected)


def test_nested_context_restores_all_fields_after_exception():
    with log_context(correlation_id="outer", receipt_id="receipt"):
        with (
            pytest.raises(ValueError),
            log_context(correlation_id="inner", job_id="job"),
        ):
            current = record()
            assert current.correlation_id == "inner"
            assert current.receipt_id == "receipt"
            assert current.job_id == "job"
            raise ValueError("failure")
        assert get_correlation_id() == "outer"
        assert record().job_id == "-"
    assert get_correlation_id() is None
    assert all(getattr(record(), field) == "-" for field in LOG_FIELDS)


def test_parallel_async_contexts_are_isolated():
    async def scenario():
        ready = asyncio.Event()
        entered = []

        async def request(cid):
            with log_context(correlation_id=cid):
                entered.append(cid)
                if len(entered) == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=2)
                assert get_correlation_id() == cid
            assert get_correlation_id() is None

        await asyncio.gather(request("first"), request("second"))

    asyncio.run(scenario())


def test_explicit_log_fields_override_context():
    with log_context(correlation_id="context", job_id="job"):
        entry = logging.makeLogRecord({"correlation_id": "explicit"})
        assert LogContextFilter().filter(entry)
        assert entry.correlation_id == "explicit"
        assert entry.job_id == "job"


def test_configuration_emits_one_formatted_event(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", root.level)
    names = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "rq",
        "rq.worker",
        "rq.job",
        "rq.queue",
        "rq.scheduler",
        "rq.cron",
        "rq.worker_pool",
    )
    for name in names:
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", list(logger.handlers))
        for attribute in ("level", "propagate", "disabled"):
            monkeypatch.setattr(logger, attribute, getattr(logger, attribute))
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    configure_logging()
    configure_logging()
    with log_context(
        correlation_id="cid", job_id="jid", receipt_id="rid", processing_version=2
    ):
        logging.getLogger("rq.worker").info("unique-event")
    output = stream.getvalue()
    assert output.count("unique-event") == 1
    for field, value in (
        ("correlation_id", "cid"),
        ("job_id", "jid"),
        ("receipt_id", "rid"),
        ("processing_version", 2),
    ):
        assert f"{field}={value}" in output


@pytest.fixture
def http_app():
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/context")
    def context():
        return {"correlation_id": get_correlation_id()}

    @app.get("/error/{status}")
    async def error(status: int):
        if status == 500:
            raise ValueError("private-error-detail")
        raise HTTPException(status_code=status, detail="Handled error")

    return app


@pytest.mark.parametrize("status", [404, 422, 500])
def test_error_responses_include_correlation_id(http_app, status):
    cid = str(uuid4())
    with TestClient(http_app, raise_server_exceptions=False) as client:
        response = client.get(f"/error/{status}", headers={"X-Correlation-ID": cid})
    assert response.status_code == status
    assert response.headers["X-Correlation-ID"] == cid
    assert "private-error-detail" not in response.text
    assert get_correlation_id() is None


def test_http_context_reaches_sync_endpoint_and_does_not_leak(http_app):
    cid = str(uuid4())
    with TestClient(http_app) as client:
        for headers in ({"X-Correlation-ID": cid}, {}, {"X-Correlation-ID": "invalid"}):
            response = client.get("/context", headers=headers)
            actual = response.headers["X-Correlation-ID"]
            assert str(UUID(actual)) == actual
            assert response.json()["correlation_id"] == actual
            assert (actual == cid) is (headers.get("X-Correlation-ID") == cid)
    assert get_correlation_id() is None


def test_concurrent_http_requests_keep_their_ids(http_app):
    async def scenario():
        ready = asyncio.Event()
        entered = []

        @http_app.get("/parallel")
        async def parallel():
            entered.append(get_correlation_id())
            if len(entered) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=2)
            return {"correlation_id": get_correlation_id()}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_app), base_url="http://test"
        ) as client:
            ids = [str(uuid4()), str(uuid4())]
            responses = await asyncio.gather(
                *(
                    client.get("/parallel", headers={"X-Correlation-ID": cid})
                    for cid in ids
                )
            )
            for cid, response in zip(ids, responses, strict=True):
                assert response.headers["X-Correlation-ID"] == cid
                assert response.json()["correlation_id"] == cid

    asyncio.run(scenario())


def test_legacy_job_has_stable_fallback_id():
    job = SimpleNamespace(id="legacy-job", args=(str(uuid4()),), meta={})
    first = get_job_log_context(job)
    assert get_job_log_context(job) == first
    assert str(UUID(first["correlation_id"])) == first["correlation_id"]
    assert first["processing_version"] == 1
    job.id = "another-job"
    assert get_job_log_context(job)["correlation_id"] != first["correlation_id"]


@pytest.mark.parametrize("fails", [False, True])
def test_worker_wraps_execution_and_restores_context(monkeypatch, fails):
    cid = str(uuid4())
    job = SimpleNamespace(id="job", args=("receipt", 2), meta={"correlation_id": cid})
    calls = []

    def execute(self, actual_job, queue):
        calls.append(actual_job)
        current = record()
        assert (
            current.correlation_id,
            current.job_id,
            current.receipt_id,
            current.processing_version,
        ) == (cid, "job", "receipt", 2)
        if fails:
            raise RuntimeError("failure")

    # Test the wrapper without forking a process on Windows.
    monkeypatch.setattr(Worker, "execute_job", execute)
    worker = object.__new__(CorrelationWorker)
    with log_context(correlation_id="outer"):
        if fails:
            with pytest.raises(RuntimeError):
                worker.execute_job(job, None)
        else:
            worker.execute_job(job, None)
        assert get_correlation_id() == "outer"
        assert record().job_id == "-"
    assert calls == [job]
