from typing import Annotated
from pydantic import BeforeValidator, EmailStr, Field, AfterValidator


def normalize_email(value: object) -> object:
    if isinstance(value, str):
        return value.strip().casefold()

    return value


def validate_registration_password(password: str):
    if password.isspace():
        raise ValueError("Пароль не может быть пустым!")
    return password


NormalizedEmail = Annotated[
    EmailStr,
    BeforeValidator(normalize_email),
]

RegistrationPassword = Annotated[
    str,
    Field(min_length=12, max_length=128),
    AfterValidator(validate_registration_password),
]

LoginPassword = Annotated[
    str,
    Field(min_length=1, max_length=128),
]
