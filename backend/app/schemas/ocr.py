from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OcrFragment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, pattern=r"\S")
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_text: str

    confidence: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    fragments: tuple[OcrFragment, ...] = ()

    @model_validator(mode="after")
    def validate_fragment_alignment(self) -> Self:
        if self.fragments and self.raw_text != "\n".join(
            part.text for part in self.fragments
        ):
            raise ValueError(
                "OCR fragments must reproduce raw_text in the original order"
            )
        return self
