from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.response import CategoryResponse
from backend.app.services.category_service import CategoryService

router = APIRouter()


@router.get("/api/categories", response_model=list[CategoryResponse])
def get_categories(
    _user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[Session, Depends(get_db)],
) -> list[CategoryResponse]:

    categories = CategoryService(db_session).get_categories()

    return [CategoryResponse.model_validate(category) for category in categories]
