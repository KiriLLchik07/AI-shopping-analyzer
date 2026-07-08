from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.request import LoginRequest
from backend.app.services.auth_service import AuthService

router = APIRouter()

@router.post("/api/auth_login")
async def auth_login(payload: LoginRequest, db_session: Session = Depends(get_db)):
    service = AuthService(db_session)
    return service.login_user(payload)

@router.post("/api/register_user")
async def register_user():
    # Здесь будет логика сохранения данных пользователя в БД
    return "success"
