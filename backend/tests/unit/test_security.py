from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.core.exceptions import InvalidCredentialsError
from backend.app.core.security import hash_password, verify_password
from backend.app.models.user import User
from backend.app.schemas.request import UserLoginRequest, UserRegisterRequest
from backend.app.schemas.response import UserResponse
from backend.app.services.auth_service import AuthService

PLAIN_PASSWORD = "strong-test-password"


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class FakeUserRepository:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.received_password_hash: str | None = None

    def get_user_by_email(self, user_mail: str) -> User | None:
        return self.user

    def register_user(
        self,
        payload: UserRegisterRequest,
        password_hash: str,
    ) -> User:
        self.received_password_hash = password_hash
        self.user = User(
            user_id=uuid4(),
            user_name=payload.user_name,
            user_surname=payload.user_surname,
            user_mail=payload.user_mail,
            user_password_hash=password_hash,
        )
        return self.user


def make_user(password: str = PLAIN_PASSWORD) -> User:
    now = datetime.now(UTC)

    return User(
        user_id=uuid4(),
        user_name="Test",
        user_surname="User",
        user_mail="test@example.com",
        user_password_hash=hash_password(password),
        created_at=now,
        updated_at=now,
    )


def test_password_hash_is_salted_and_verifiable() -> None:
    first_hash = hash_password(PLAIN_PASSWORD)
    second_hash = hash_password(PLAIN_PASSWORD)

    assert first_hash.startswith("$argon2id$")
    assert first_hash != second_hash
    assert PLAIN_PASSWORD not in first_hash
    assert verify_password(PLAIN_PASSWORD, first_hash)
    assert not verify_password("wrong-password", first_hash)


def test_registration_hashes_password_before_repository() -> None:
    session = FakeSession()
    repository = FakeUserRepository()
    service = AuthService(session)  # type: ignore[arg-type]
    service.repository = repository  # type: ignore[assignment]
    payload = UserRegisterRequest(
        user_name="Test",
        user_surname="User",
        user_mail="test@example.com",
        user_password=PLAIN_PASSWORD,
    )

    user = service.register_user(payload)

    assert session.committed
    assert repository.received_password_hash != PLAIN_PASSWORD
    assert verify_password(PLAIN_PASSWORD, user.user_password_hash)


def test_login_verifies_password_hash() -> None:
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    service.repository = FakeUserRepository(make_user())  # type: ignore[assignment]

    user = service.login_user(
        UserLoginRequest(
            user_mail="test@example.com",
            user_password=PLAIN_PASSWORD,
        )
    )

    assert user.user_mail == "test@example.com"


def test_login_rejects_wrong_password() -> None:
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    service.repository = FakeUserRepository(make_user())  # type: ignore[assignment]

    with pytest.raises(InvalidCredentialsError) as exception:
        service.login_user(
            UserLoginRequest(
                user_mail="test@example.com",
                user_password="wrong-password",
            )
        )

    assert exception.value.detail == "Invalid email or password"


def test_user_response_does_not_expose_password_hash() -> None:
    response_data = UserResponse.model_validate(make_user()).model_dump()

    assert "user_password" not in response_data
    assert "user_password_hash" not in response_data
