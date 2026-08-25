from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.validation import NormalizedEmail, RegistrationPassword, LoginPassword

class UserLoginRequest(BaseModel):
    user_mail: NormalizedEmail
    user_password: LoginPassword

class UserRegisterRequest(BaseModel):
    user_name: str
    user_surname: str
    user_mail: NormalizedEmail
    user_password: RegistrationPassword

class ChangePasswordRequest(BaseModel):
    current_password: LoginPassword
    new_password: RegistrationPassword

class ReceiptListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
