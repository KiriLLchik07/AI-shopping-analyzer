from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.validation import (
    LoginPassword,
    NormalizedEmail,
    RegistrationPassword,
)


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
    date_from: date | None = None
    date_to: date | None = None
    store_name: str | None = Field(default=None, min_length=1, max_length=100)
    status: ReceiptStatus | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be later then date_to")

        return self


class ReceiptUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_name: str | None = Field(default=None, min_length=1, max_length=100)
    store_inn: str | None = Field(default=None, max_length=12)
    purchase_datetime: datetime | None = None
    total_amount: Decimal | None = Field(default=None, gt=0)
    payment_type: str | None = Field(default=None, max_length=30)
    fiscal_drive_number: str | None = Field(default=None, max_length=16)
    fiscal_document_number: str | None = None
    fiscal_sign: str | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")

        return self
