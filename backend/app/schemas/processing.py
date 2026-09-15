from pydantic import BaseModel, ConfigDict

from backend.app.schemas.request import ReceiptItemCreateRequest


class ReceiptProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_ocr_text: str | None = None
    items: tuple[ReceiptItemCreateRequest, ...]
