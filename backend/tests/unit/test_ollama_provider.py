import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from backend.app.core.config import LlmSettings
from backend.app.llm import factory
from backend.app.llm.exceptions import (
    LlmConfigurationError,
    LlmResponseValidationError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from backend.app.llm.ollama_provider import OllamaLlmProvider
from backend.app.schemas.llm import LlmRequest


class Summary(BaseModel):
    summary: str


def settings(**values):
    return LlmSettings(_env_file=None, **values)


def request():
    return LlmRequest(
        prompt_version="monthly-v1",
        system_prompt="PRIVATE SYSTEM",
        payload={"total_amount": "500.00"},
    )


def envelope(**updates):
    return {
        "message": {"role": "assistant", "content": '{"summary":"Отчёт"}'},
        "done": True,
        "done_reason": "stop",
        **updates,
    }


def local_model(**updates):
    return {"capabilities": ["completion", "thinking"], **updates}


def provider(handler, **config):
    return OllamaLlmProvider(settings(**config), transport=httpx.MockTransport(handler))


def test_local_schema_request_and_response():
    seen = []

    def handle(req):
        seen.append(req)
        return httpx.Response(
            200, json=local_model() if req.url.path == "/api/show" else envelope()
        )

    value = provider(handle)
    assert value.generate(request(), response_model=Summary) == Summary(summary="Отчёт")
    assert value.provider_name == "ollama"
    assert value.model_name == "qwen3.5:4b"
    assert [r.url.path for r in seen] == ["/api/show", "/api/chat"]
    assert all(r.url.host == "127.0.0.1" for r in seen)
    body = json.loads(seen[-1].content)
    assert body["model"] == "qwen3.5:4b"
    assert body["format"] == Summary.model_json_schema()
    assert body["stream"] is body["think"] is False
    assert body["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 8192,
        "num_predict": 2048,
    }
    assert body["keep_alive"] == 300
    assert json.loads(body["messages"][1]["content"]) == request().payload
    assert "JSON Schema:" in body["messages"][0]["content"]
    assert "tools" not in body
    assert all("images" not in m for m in body["messages"])
    assert seen[-1].extensions["timeout"] == {
        "connect": 3.0,
        "read": 90.0,
        "write": 90.0,
        "pool": 90.0,
    }


def test_optional_thinking_control_can_be_omitted():
    def handle(req):
        if req.url.path == "/api/chat":
            assert "think" not in json.loads(req.content)
        return httpx.Response(
            200, json=local_model() if req.url.path == "/api/show" else envelope()
        )

    provider(handle, think=None).generate(request(), response_model=Summary)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_status_retries_then_succeeds(status, monkeypatch, caplog):
    attempts, sleeps = [], []
    monkeypatch.setattr("backend.app.llm.ollama_provider.time.sleep", sleeps.append)

    def handle(req):
        if req.url.path == "/api/show":
            return httpx.Response(200, json=local_model())
        attempts.append(req)
        return (
            httpx.Response(status, text="PRIVATE ERROR")
            if len(attempts) == 1
            else httpx.Response(200, json=envelope())
        )

    assert (
        provider(handle).generate(request(), response_model=Summary).summary == "Отчёт"
    )
    assert len(attempts) == 2
    assert sleeps == [1]
    assert "llm_unavailable" in caplog.text
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    "kind,expected",
    [
        (httpx.ReadTimeout, LlmTimeoutError),
        (httpx.ConnectTimeout, LlmTimeoutError),
        (httpx.ConnectError, LlmUnavailableError),
        (httpx.RemoteProtocolError, LlmUnavailableError),
    ],
)
def test_transport_failures_are_bounded_and_safe(kind, expected, monkeypatch, caplog):
    attempts, sleeps = [], []
    monkeypatch.setattr("backend.app.llm.ollama_provider.time.sleep", sleeps.append)

    def handle(req):
        attempts.append(req)
        raise kind("PRIVATE TRANSPORT DETAILS", request=req)

    with pytest.raises(expected) as caught:
        provider(handle).generate(request(), response_model=Summary)
    assert len(attempts) == 3
    assert sleeps == [1, 3]
    assert "PRIVATE" not in str(caught.value) + caplog.text


def test_retries_can_be_disabled():
    seen = []

    def handle(req):
        seen.append(req)
        return httpx.Response(503)

    with pytest.raises(LlmUnavailableError):
        provider(handle, retry_intervals_seconds=()).generate(
            request(), response_model=Summary
        )
    assert len(seen) == 1


def test_timeout_while_reading_chat_body_closes_response_and_retries(monkeypatch):
    attempts, sleeps, streams = [], [], []
    monkeypatch.setattr("backend.app.llm.ollama_provider.time.sleep", sleeps.append)

    class InterruptedStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'{"message":'
            raise httpx.ReadTimeout("PRIVATE READ DETAILS")

        def close(self):
            self.closed = True

    def handle(req):
        if req.url.path == "/api/show":
            return httpx.Response(200, json=local_model())
        attempts.append(req)
        if len(attempts) == 1:
            stream = InterruptedStream()
            streams.append(stream)
            return httpx.Response(200, stream=stream)
        return httpx.Response(200, json=envelope())

    assert (
        provider(handle).generate(request(), response_model=Summary).summary == "Отчёт"
    )
    assert len(attempts) == 2
    assert sleeps == [1]
    assert streams[0].closed


@pytest.mark.parametrize("path", ["/api/show", "/api/chat"])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 302])
def test_configuration_errors_and_redirects_are_not_retried(path, status):
    seen = []

    def handle(req):
        seen.append(req.url.path)
        return (
            httpx.Response(
                status, text="PRIVATE", headers={"Location": "https://external.example"}
            )
            if req.url.path == path
            else httpx.Response(200, json=local_model())
        )

    with pytest.raises(LlmConfigurationError) as caught:
        provider(handle).generate(request(), response_model=Summary)
    assert seen == (
        ["/api/show"] if path == "/api/show" else ["/api/show", "/api/chat"]
    )
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        envelope(done=False),
        envelope(done_reason="length"),
        envelope(message={"role": "user", "content": "{}"}),
        envelope(message={"role": "assistant", "content": "PRIVATE INVALID JSON"}),
        envelope(message={"role": "assistant", "content": "{}"}),
        envelope(
            message={
                "role": "assistant",
                "content": '{"summary":"ok"}',
                "tool_calls": [{"function": {"name": "update_receipt"}}],
            }
        ),
        {"error": "PRIVATE ERROR"},
    ],
)
def test_bad_or_truncated_output_is_not_retried(body):
    seen = []

    def handle(req):
        seen.append(req.url.path)
        return httpx.Response(
            200, json=local_model() if req.url.path == "/api/show" else body
        )

    with pytest.raises(LlmResponseValidationError) as caught:
        provider(handle).generate(request(), response_model=Summary)
    assert seen == ["/api/show", "/api/chat"]
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize(
    "info",
    [
        local_model(remote_host="https://external.example"),
        local_model(remote_model="cloud-alias"),
        local_model(capabilities=["embedding"]),
    ],
)
def test_cloud_alias_or_embedding_model_never_receives_payload(info):
    seen = []

    def handle(req):
        seen.append(req)
        return httpx.Response(200, json=info)

    with pytest.raises(LlmConfigurationError):
        provider(handle).generate(request(), response_model=Summary)
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {"model": "qwen3.5:4b"}


def test_oversized_response_is_closed_and_rejected():
    class LargeStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b"X" * 2048

        def close(self):
            self.closed = True

    stream = LargeStream()

    def handle(req):
        return (
            httpx.Response(200, json=local_model())
            if req.url.path == "/api/show"
            else httpx.Response(200, stream=stream)
        )

    with pytest.raises(LlmResponseValidationError):
        provider(handle, max_response_bytes=1024).generate(
            request(), response_model=Summary
        )
    assert stream.closed


@pytest.mark.parametrize(
    "url",
    [
        "https://external.example",
        "http://127.0.0.1.evil.example",
        "http://user:pass@localhost:11434",
        "http://127.0.0.1:11434/path",
        "http://127.0.0.1:11434?key=secret",
        "ftp://localhost",
        "http://localhost:0",
    ],
)
def test_settings_reject_nonlocal_or_ambiguous_urls(url):
    with pytest.raises(ValidationError):
        settings(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434/",
        "http://[::1]:11434",
        "http://host.docker.internal:11434",
    ],
)
def test_local_and_docker_urls_are_supported(url):
    assert settings(base_url=url).base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "values",
    [
        {"model_name": "qwen3:cloud"},
        {"model_name": " "},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"retry_intervals_seconds": (1, 2, 3)},
        {"retry_intervals_seconds": (3, 1)},
        {"retry_intervals_seconds": (-1,)},
        {"num_ctx": 999999},
        {"num_predict": 0},
    ],
)
def test_settings_validate_generation_limits(values):
    with pytest.raises(ValidationError):
        settings(**values)


def test_factory_returns_cached_local_provider(monkeypatch):
    factory.get_llm_provider.cache_clear()
    monkeypatch.setattr(factory, "llm_settings", settings())
    try:
        first = factory.get_llm_provider()
        assert isinstance(first, OllamaLlmProvider)
        assert factory.get_llm_provider() is first
    finally:
        factory.get_llm_provider.cache_clear()
