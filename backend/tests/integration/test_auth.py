import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import verify_password
from backend.app.models.user import User
from backend.app.services.session_service import redis_client


pytestmark = pytest.mark.integration


USER_PAYLOAD = {
    "user_name": "Test",
    "user_surname": "User",
    "user_mail": "test@example.com",
    "user_password": "strong-test-password",
}


def register_user(client: TestClient):
    return client.post("/api/register_user", json=USER_PAYLOAD)


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

    login_response = client.post(
        "/api/auth_login",
        json={
            "user_mail": USER_PAYLOAD["user_mail"],
            "user_password": USER_PAYLOAD["user_password"],
        },
    )

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


def test_login_with_wrong_password_does_not_create_session(
    client: TestClient,
) -> None:
    assert register_user(client).status_code == 201

    response = client.post(
        "/api/auth_login",
        json={
            "user_mail": USER_PAYLOAD["user_mail"],
            "user_password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert "session_id" not in client.cookies
    assert redis_client.dbsize() == 0


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    assert register_user(client).status_code == 201

    response = register_user(client)

    assert response.status_code == 409
