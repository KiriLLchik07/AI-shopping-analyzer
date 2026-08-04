from pydantic import BaseModel
from backend.app.schemas.validation import NormalizedEmail, RegistrationPassword, LoginPassword

class UserLoginRequest(BaseModel):
    user_mail: NormalizedEmail
    user_password: LoginPassword

class UserRegisterRequest(BaseModel):
    user_name: str
    user_surname: str
    user_mail: NormalizedEmail
    user_password: RegistrationPassword

