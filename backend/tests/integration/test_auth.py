import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import setting
from backend.app.core.security import verify_password
from backend.app.main import app
from backend.app.models.user import User
from backend.app.services.session_service import redis_client

pytestmark = pytest.mark.integration


USER_PAYLOAD = {
    "user_name": "Test",
    "user_surname": "User",
    "user_mail": "test@example.com",
    "user_password": "strong-test-password",
}

NEW_PASSWORD = "new-strong-test-password"


def register_user(client: TestClient):
    return client.post("/api/register_user", json=USER_PAYLOAD)


def login_user(client: TestClient, password: str):
    return client.post(
        "/api/auth_login",
        json={
            "user_mail": USER_PAYLOAD["user_mail"],
            "user_password": password,
        },
    )


def change_password(
    client: TestClient,
    current_password: str,
    new_password: str,
):
    return client.put(
        "/api/auth/password",
        json={
            "current_password": current_password,
            "new_password": new_password,
        },
    )


def assert_password_is_not_exposed(response_data: dict) -> None:
    assert "user_password" not in response_data
    assert "user_password_hash" not in response_data


def test_registration_stores_only_password_hash(
    client: TestClient,
    db_session: Session,
) -> None:
    response = register_user(client)

    assert response.status_code == 201
    assert_password_is_not_exposed(response.json())

    user = db_session.scalars(
        select(User).where(User.user_mail == USER_PAYLOAD["user_mail"])
    ).one()

    assert user.user_password_hash != USER_PAYLOAD["user_password"]
    assert user.user_password_hash.startswith("$argon2id$")
    assert verify_password(USER_PAYLOAD["user_password"], user.user_password_hash)


def test_login_session_me_and_logout(client: TestClient) -> None:
    assert register_user(client).status_code == 201

    login_response = login_user(client, USER_PAYLOAD["user_password"])

    assert login_response.status_code == 200
    assert_password_is_not_exposed(login_response.json())
    assert "session_id" in client.cookies
    assert "HttpOnly" in login_response.headers["set-cookie"]

    session_keys = list(redis_client.scan_iter("auth_session:*"))
    assert len(session_keys) == 1
    assert redis_client.ttl(session_keys[0]) > 0

    me_response = client.get("/api/auth/me")

    assert me_response.status_code == 200
    assert me_response.json()["user_mail"] == USER_PAYLOAD["user_mail"]
    assert_password_is_not_exposed(me_response.json())

    logout_response = client.post("/api/logout")

    assert logout_response.status_code == 204
    assert "session_id" not in client.cookies
    assert redis_client.dbsize() == 0
    assert client.get("/api/auth/me").status_code == 401


def test_me_without_cookie_returns_401(client: TestClient) -> None:
    assert "session_id" not in client.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_deleted_redis_session_returns_401(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    session_keys = list(redis_client.scan_iter("auth_session:*"))
    assert len(session_keys) == 1
    redis_client.delete(session_keys[0])

    assert "session_id" in client.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_expired_redis_session_returns_401(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    session_keys = list(redis_client.scan_iter("auth_session:*"))
    assert len(session_keys) == 1
    redis_client.expire(session_keys[0], 1)

    deadline = time.monotonic() + 3
    while redis_client.exists(session_keys[0]) and time.monotonic() < deadline:
        time.sleep(0.05)

    assert redis_client.exists(session_keys[0]) == 0
    assert "session_id" in client.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_previous_cookie(client: TestClient) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    previous_session_id = client.cookies.get("session_id")
    assert previous_session_id is not None
    assert client.post("/api/logout").status_code == 204

    with TestClient(app) as client_with_old_cookie:
        client_with_old_cookie.cookies.set(
            "session_id",
            previous_session_id,
            path="/",
        )
        assert client_with_old_cookie.get("/api/auth/me").status_code == 401


def test_login_with_wrong_password_does_not_create_session(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201

    response = login_user(client, "wrong-password")

    assert response.status_code == 401
    assert "session_id" not in client.cookies
    assert list(redis_client.scan_iter("auth_session:*")) == []

    failure_keys = list(redis_client.scan_iter("auth:login:failures:*"))
    assert len(failure_keys) == 1
    assert redis_client.get(failure_keys[0]) == "1"
    assert redis_client.ttl(failure_keys[0]) > 0


def test_login_rate_limit_blocks_after_max_failures(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201

    for _ in range(setting.login_rate_limit_attempts - 1):
        assert login_user(client, "wrong-password").status_code == 401

    blocked_response = login_user(client, "wrong-password")

    assert blocked_response.status_code == 429
    assert int(blocked_response.headers["Retry-After"]) > 0
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 429
    assert list(redis_client.scan_iter("auth_session:*")) == []

    failure_keys = list(redis_client.scan_iter("auth:login:failures:*"))
    assert len(failure_keys) == 1
    assert redis_client.get(failure_keys[0]) == str(setting.login_rate_limit_attempts)
    assert (
        0
        < redis_client.ttl(failure_keys[0])
        <= (setting.login_rate_limit_window_seconds)
    )


def test_successful_login_resets_failure_counter(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, "wrong-password").status_code == 401
    assert len(list(redis_client.scan_iter("auth:login:failures:*"))) == 1

    response = login_user(client, USER_PAYLOAD["user_password"])

    assert response.status_code == 200
    assert list(redis_client.scan_iter("auth:login:failures:*")) == []
    assert len(list(redis_client.scan_iter("auth_session:*"))) == 1


def test_login_is_allowed_after_rate_limit_expires(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setting, "login_rate_limit_attempts", 2)
    monkeypatch.setattr(setting, "login_rate_limit_window_seconds", 1)
    assert register_user(client).status_code == 201

    assert login_user(client, "wrong-password").status_code == 401
    assert login_user(client, "wrong-password").status_code == 429

    deadline = time.monotonic() + 3
    while (
        list(redis_client.scan_iter("auth:login:failures:*"))
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)

    assert list(redis_client.scan_iter("auth:login:failures:*")) == []
    assert login_user(client, "wrong-password").status_code == 401


def test_change_password_rejects_wrong_current_password(
    client: TestClient,
    db_session: Session,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    response = change_password(client, "wrong-password", NEW_PASSWORD)

    assert response.status_code == 400
    assert "session_id" in client.cookies
    assert client.get("/api/auth/me").status_code == 200
    assert len(list(redis_client.scan_iter("auth_session:*"))) == 1
    assert len(list(redis_client.scan_iter("auth_user_sessions:*"))) == 1

    user = db_session.scalars(
        select(User).where(User.user_mail == USER_PAYLOAD["user_mail"])
    ).one()
    assert verify_password(USER_PAYLOAD["user_password"], user.user_password_hash)
    assert not verify_password(NEW_PASSWORD, user.user_password_hash)


def test_change_password_rejects_current_password_as_new(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    response = change_password(
        client,
        USER_PAYLOAD["user_password"],
        USER_PAYLOAD["user_password"],
    )

    assert response.status_code == 400
    assert "session_id" in client.cookies
    assert client.get("/api/auth/me").status_code == 200


def test_change_password_revokes_all_sessions(
    client: TestClient,
    db_session: Session,
) -> None:
    assert register_user(client).status_code == 201
    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 200

    with TestClient(app) as second_client:
        assert (
            login_user(second_client, USER_PAYLOAD["user_password"]).status_code == 200
        )
        assert len(list(redis_client.scan_iter("auth_session:*"))) == 2

        user_session_keys = list(redis_client.scan_iter("auth_user_sessions:*"))
        assert len(user_session_keys) == 1
        assert redis_client.scard(user_session_keys[0]) == 2

        response = change_password(
            client,
            USER_PAYLOAD["user_password"],
            NEW_PASSWORD,
        )

        assert response.status_code == 204
        assert response.content == b""
        assert "session_id" not in client.cookies
        assert client.get("/api/auth/me").status_code == 401
        assert second_client.get("/api/auth/me").status_code == 401

    assert list(redis_client.scan_iter("auth_session:*")) == []
    assert list(redis_client.scan_iter("auth_user_sessions:*")) == []

    user = db_session.scalars(
        select(User).where(User.user_mail == USER_PAYLOAD["user_mail"])
    ).one()
    assert not verify_password(USER_PAYLOAD["user_password"], user.user_password_hash)
    assert verify_password(NEW_PASSWORD, user.user_password_hash)

    assert login_user(client, USER_PAYLOAD["user_password"]).status_code == 401
    assert login_user(client, NEW_PASSWORD).status_code == 200


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    assert register_user(client).status_code == 201

    response = register_user(client)

    assert response.status_code == 409
