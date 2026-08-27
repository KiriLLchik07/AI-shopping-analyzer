from sqlalchemy.orm import Session
from sqlalchemy import select
from uuid import UUID

from backend.app.models.user import User
from backend.app.schemas.request import UserRegisterRequest


class UserRepository:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def get_user_by_email(self, user_mail: str) -> User | None:
        query = select(User).where(User.user_mail == user_mail)
        return self.db_session.scalars(query).first()

    def register_user(self, payload: UserRegisterRequest, password_hash: str) -> User:
        user = User(
            user_name=payload.user_name,
            user_surname=payload.user_surname,
            user_mail=payload.user_mail,
            user_password_hash=password_hash,
        )

        self.db_session.add(user)
        self.db_session.flush()
        return user

    def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.db_session.get(User, user_id)
