from pydantic import BaseModel, ConfigDict, Field


class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_text: str

    confidence: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
