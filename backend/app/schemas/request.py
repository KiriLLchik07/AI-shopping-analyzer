from pydantic import BaseModel

class UserLoginRequest(BaseModel):
    user_mail: str
    user_password: str

class UserRegisterRequest(BaseModel):
    user_name: str
    user_surname: str
    user_mail: str
    user_password: str

