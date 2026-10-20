from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Angle = Literal[0, 90, 180, 270]


class OrientationPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    correction_angle: Angle
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class OrientationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    accepted: bool
    correction_angle: Angle | None
    reason: Literal[
        "consensus",
        "confident_disagreement",
        "insufficient_confident_votes",
        "single_prediction",
        "low_confidence",
    ]
    votes: tuple[OrientationPrediction, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_angle(self) -> Self:
        if self.accepted != (self.correction_angle is not None):
            raise ValueError("Only accepted decisions must have an angle")
        return self


class OrientationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    exif_corrected: bool
    decision: OrientationDecision
    model_rotation_enabled: bool
    applied_angle: Angle
    needs_review: bool
    review_reason: str | None
