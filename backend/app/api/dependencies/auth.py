from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from backend.app.core.exceptions import InvalidSessionError, SessionRequiredError
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.repositories.user_repository import UserRepository
from backend.app.services.session_service import get_session_user_id


def get_current_user(
    db_session: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie()] = None,
) -> User:

    if session_id is None:
        raise SessionRequiredError

    user_id = get_session_user_id(session_id)
    user = UserRepository(db_session).get_user_by_id(user_id) if user_id else None

    if user is None:
        raise InvalidSessionError

    return user
