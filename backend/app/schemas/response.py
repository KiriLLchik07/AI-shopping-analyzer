from pydantic import BaseModel, ConfigDict
from uuid import UUID
from typing import Literal
from datetime import datetime
from decimal import Decimal

from backend.app.models.enums import ReceiptStatus


class UserResponse(BaseModel):
    user_id: UUID
    user_name: str
    user_surname: str
    user_mail: str
    user_age: int | None
    user_country: str | None
    user_city: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Health сервис


class HealthLiveResponse(BaseModel):
    status: Literal["ok"]


class HealthServicesResponse(BaseModel):
    postgresql: bool
    redis: bool
    minio: bool


class HealthReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    services: HealthServicesResponse


class ReceiptResponse(BaseModel):
    receipt_id: UUID
    receipt_user_id: UUID
    store_name: str | None
    store_inn: str | None
    purchase_datetime: datetime | None
    total_amount: Decimal | None
    payment_type: str | None
    fiscal_drive_number: str | None
    fiscal_document_number: str | None
    fiscal_sign: str | None
    image_url: str
    raw_ocr_text: str | None
    status: ReceiptStatus
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReceiptListResponse(BaseModel):
    items: list[ReceiptResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
