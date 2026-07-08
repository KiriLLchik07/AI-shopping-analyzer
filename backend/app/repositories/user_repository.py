from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.user import User

class UserRepository:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def get_user_by_login_data(self, user_password, user_mail) -> User:
        query = (
            select(User).where(User.user_id == (user_password, user_mail))
        )
        return self.db_session.scalars(query).first()
