import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.config import CorsSettings, cors_settings
from backend.app.main import app, unhandled_exception_handler


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "https://*.example.com",
        "http://localhost:5173/",
        "http://localhost:5173/path",
        "http://localhost:5173?query=1",
        "http://localhost:5173#hash",
        "https://user:pass@example.com",
        "ftp://example.com",
        "http://localhost:0",
        "http://localhost:99999",
        " http://localhost:5173",
    ],
)
def test_cors_config_rejects_non_origins(origin):
    with pytest.raises(ValidationError):
        CorsSettings(_env_file=None, allow_origins=(origin,))


def test_cors_config_supports_exact_origins_and_empty_allowlist():
    origins = ("http://localhost:5173", "https://app.example.com")
    assert CorsSettings(_env_file=None, allow_origins=origins).allow_origins == origins
    assert CorsSettings(_env_file=None, allow_origins=()).allow_origins == ()


def test_cors_config_reads_json_environment(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["https://app.example.com"]')
    assert CorsSettings(_env_file=None).allow_origins == ("https://app.example.com",)


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_preflight_allows_configured_origin_and_credentials(client, method):
    origin = cors_settings.allow_origins[0]
    response = client.options(
        "/api/receipts",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type,x-correlation-id",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in response.headers["vary"]


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost:5174", "null"]
)
def test_preflight_rejects_other_origins(client, origin):
    response = client.options(
        "/api/auth_login",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("path,status", [("/health/live", 200), ("/not-found", 404)])
def test_cors_response_exposes_correlation_id(client, path, status):
    origin = cors_settings.allow_origins[0]
    response = client.get(path, headers={"Origin": origin})
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "X-Correlation-ID" in response.headers["access-control-expose-headers"]
    assert "Retry-After" in response.headers["access-control-expose-headers"]
    assert response.headers["x-correlation-id"]


def test_other_origin_gets_no_allow_origin_header(client):
    response = client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "method,header", [("TRACE", "content-type"), ("POST", "x-unapproved-header")]
)
def test_preflight_rejects_unapproved_method_or_header(client, method, header):
    response = client.options(
        "/api/receipts",
        headers={
            "Origin": cors_settings.allow_origins[0],
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": header,
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("allowed", [True, False])
def test_unhandled_error_includes_cors_only_for_allowed_origin(allowed):
    test_app = FastAPI()
    test_app.add_exception_handler(Exception, unhandled_exception_handler)

    @test_app.get("/error")
    async def error():
        raise RuntimeError("PRIVATE ERROR")

    origin = cors_settings.allow_origins[0] if allowed else "https://evil.example"
    with TestClient(test_app, raise_server_exceptions=False) as client:
        response = client.get("/error", headers={"Origin": origin})
    assert response.status_code == 500
    assert "PRIVATE" not in response.text
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
    if allowed:
        assert response.headers["access-control-allow-credentials"] == "true"
