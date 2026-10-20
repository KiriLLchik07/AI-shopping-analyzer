from uuid import UUID

from backend.app.schemas.items import ReceiptItemData
from backend.app.schemas.orientation import OrientationReport
from backend.app.schemas.parsing import ReceiptParsingResult
from pydantic import BaseModel, ConfigDict


class ReceiptPreprocessingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    image: bytes
    orientation_report: OrientationReport | None = None


class ReceiptProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_ocr_text: str | None = None
    items: tuple[ReceiptItemData, ...]
    parsed_receipt: ReceiptParsingResult | None = None


class ReceiptProcessingInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    image_object_key: str


class ReceiptProcessTicket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    processing_version: int
