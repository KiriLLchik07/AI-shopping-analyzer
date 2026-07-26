from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.app.schemas.request import UserRegisterRequest, UserLoginRequest
from backend.app.repositories.user_repository import UserRepository
from backend.app.serializer.serializer import user_to_dto

class AuthService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.repository = UserRepository(db_session)

    def login_user(self, payload: UserLoginRequest) -> dict:
        user = self.repository.get_user_by_email(payload.user_mail)
        
        if user is None or user.user_password != payload.user_password:
            raise HTTPException(401, "Пользователь с такими данными не найден. Проверьте почту или пароль. Если вы еще не регистрировались, то сделайте это!")

        return user_to_dto(user)

    def register_user(self, payload: UserRegisterRequest) -> dict:
        if_user = self.repository.get_user_by_email(payload.user_mail)

        if if_user:
            raise HTTPException(409, "Пользователь с такой почтой уже существует!")
        else:
            user = self.repository.register_user(payload)
            self.db_session.commit()
            return user_to_dto(user)

