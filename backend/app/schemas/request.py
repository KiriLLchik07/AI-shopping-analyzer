from pydantic import BaseModel

class LoginRequest(BaseModel):
    user_mail: str
    password: str


