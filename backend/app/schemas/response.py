from pydantic import BaseModel
from uuid import UUID

class LoginResponse(BaseModel):
    user_id: UUID
    success: str

    # Нужны еще поля
