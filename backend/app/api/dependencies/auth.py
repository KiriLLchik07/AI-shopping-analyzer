from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.repositories.user_repository import UserRepository
from backend.app.services.session_service import get_session_user_id


def get_current_user(
    session_id: Annotated[str | None, Cookie()] = None,
    db_session: Session = Depends(get_db),
) -> User:

    if session_id is None:
        raise HTTPException(status_code=401, detail="Необходим вход")

    user_id = get_session_user_id(session_id)
    user = UserRepository(db_session).get_user_by_id(user_id) if user_id else None

    if user is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна")

    return user
