from sqlalchemy.orm import Session

from backend.app.schemas.request import LoginRequest
from backend.app.repositories.user_repository import UserRepository

class AuthService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.repository = UserRepository(db_session)

    def login_user(self, payload: LoginRequest) -> dict:
        user = self.repository.get_user_by_login_data(payload)
        
        if user is None or user.user_password != payload.password:
            raise ValueError(f"Пользователь с такими данными не найден. Проверьте почту или пароль. Если вы еще не регистрировались, то сделайте это!")

        # Нужен слой serialize
