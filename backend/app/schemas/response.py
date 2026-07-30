from pydantic import BaseModel, ConfigDict
from uuid import UUID

class UserResponse(BaseModel):
    user_id: UUID
    user_name: str
    user_surname: str
    user_mail: str
    user_age: int | None
    user_country: str | None
    user_city: str | None
    model_config = ConfigDict(from_attributes=True)
