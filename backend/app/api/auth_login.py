from fastapi import APIRouter, Depends, Response, Cookie
from sqlalchemy.orm import Session
from typing import Annotated

from backend.app.db.session import get_db
from backend.app.schemas.request import UserLoginRequest, UserRegisterRequest
from backend.app.services.auth_service import AuthService
from backend.app.services.session_service import create_session, delete_session
from backend.app.core.config import setting
from backend.app.serializer.serializer import user_to_dto
from backend.app.models.user import User
from backend.app.api.dependencies.auth import get_current_user

router = APIRouter()

@router.post("/api/auth_login")
def auth_login(payload: UserLoginRequest, response: Response, db_session: Session = Depends(get_db)):
    user = AuthService(db_session).login_user(payload)
    session_id = create_session(user.user_id)

    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=setting.session_ttl_seconds,
        httponly=True,
        secure=setting.cookie_secure,
        samesite="lax",
        path='/'
    )

    return user_to_dto(user)

@router.post("/api/register_user", status_code=201)
def register_user(payload: UserRegisterRequest, db_session: Session = Depends(get_db)):
    service = AuthService(db_session)
    return service.register_user(payload)

@router.post("/api/logout", status_code=204)
def logout(response: Response, session_id: Annotated[str | None, Cookie()] = None):

    if session_id:
        delete_session(session_id)

    response.delete_cookie(key="session_id", path="/")

@router.get("/api/auth/me")
def get_me(user: User = Depends(get_current_user)):
    return user_to_dto(user)
