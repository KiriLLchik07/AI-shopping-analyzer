from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.request import ReceiptItemCreateRequest


class ReceiptProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_ocr_text: str | None = None
    items: tuple[ReceiptItemCreateRequest, ...]


class ReceiptProcessingInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    image_object_key: str


class ReceiptProcessTicket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    processing_version: int
