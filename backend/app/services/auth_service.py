from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    PasswordReuseError,
)
from backend.app.core.security import hash_password, verify_password
from backend.app.models.user import User
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.request import (
    ChangePasswordRequest,
    UserLoginRequest,
    UserRegisterRequest,
)
from backend.app.services.session_service import delete_all_user_sessions


class AuthService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.repository = UserRepository(db_session)

    def login_user(self, payload: UserLoginRequest) -> User:
        user = self.repository.get_user_by_email(payload.user_mail)

        if user is None or not verify_password(
            payload.user_password, user.user_password_hash
        ):
            raise InvalidCredentialsError

        return user

    def register_user(self, payload: UserRegisterRequest) -> User:
        existing_user = self.repository.get_user_by_email(payload.user_mail)

        if existing_user is not None:
            raise EmailAlreadyExistsError

        hashed_password = hash_password(payload.user_password)
        user = self.repository.register_user(
            payload,
            password_hash=hashed_password,
        )
        self.db_session.commit()

        return user

    def change_password(self, user: User, payload: ChangePasswordRequest) -> None:
        if not verify_password(payload.current_password, user.user_password_hash):
            raise InvalidCurrentPasswordError

        if verify_password(payload.new_password, user.user_password_hash):
            raise PasswordReuseError

        user.user_password_hash = hash_password(payload.new_password)
        self.db_session.flush()
        delete_all_user_sessions(user.user_id)
        self.db_session.commit()
