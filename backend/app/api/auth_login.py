from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.request import UserLoginRequest, UserRegisterRequest
from backend.app.services.auth_service import AuthService

router = APIRouter()

@router.post("/api/auth_login")
def auth_login(payload: UserLoginRequest, db_session: Session = Depends(get_db)):
    service = AuthService(db_session)
    return service.login_user(payload)

@router.post("/api/register_user", status_code=201)
def register_user(payload: UserRegisterRequest, db_session: Session = Depends(get_db)):
    service = AuthService(db_session)
    return service.register_user(payload)
