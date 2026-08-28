from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.orm import Session

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.config import setting
from backend.app.core.exceptions import (
    InvalidCredentialsError,
    TooManyLoginAttemptsError,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.request import (
    ChangePasswordRequest,
    UserLoginRequest,
    UserRegisterRequest,
)
from backend.app.schemas.response import UserResponse
from backend.app.services.auth_service import AuthService
from backend.app.services.login_rate_limit_service import (
    get_retry_after,
    record_failure,
    reset_failures,
)
from backend.app.services.session_service import create_session, delete_session

router = APIRouter()


@router.post("/api/auth_login")
def auth_login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db_session: Session = Depends(get_db),
) -> UserResponse:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = get_retry_after(payload.user_mail, client_ip)
    if retry_after is not None:
        raise TooManyLoginAttemptsError(retry_after)
    try:
        user = AuthService(db_session).login_user(payload)
    except InvalidCredentialsError as error:
        attempts = record_failure(payload.user_mail, client_ip)
        if attempts >= setting.login_rate_limit_attempts:
            retry_after = (
                get_retry_after(payload.user_mail, client_ip)
                or setting.login_rate_limit_window_seconds
            )
            raise TooManyLoginAttemptsError(retry_after) from error
        raise

    reset_failures(payload.user_mail, client_ip)

    session_id = create_session(user.user_id)

    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=setting.session_ttl_seconds,
        httponly=True,
        secure=setting.cookie_secure,
        samesite="lax",
        path="/",
    )

    return UserResponse.model_validate(user)


@router.post("/api/register_user", status_code=201)
def register_user(
    payload: UserRegisterRequest, db_session: Session = Depends(get_db)
) -> UserResponse:
    user = AuthService(db_session).register_user(payload)
    return UserResponse.model_validate(user)


@router.post("/api/logout", status_code=204)
def logout(response: Response, session_id: Annotated[str | None, Cookie()] = None):
    if session_id:
        delete_session(session_id)

    response.delete_cookie(key="session_id", path="/")


@router.get("/api/auth/me")
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.put("/api/auth/password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db),
) -> None:
    AuthService(db_session).change_password(user, payload)
    response.delete_cookie(key="session_id", path="/")
