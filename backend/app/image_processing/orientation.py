import logging
import warnings
from abc import ABC, abstractmethod
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from backend.app.schemas.orientation import (
    OrientationDecision,
    OrientationPrediction,
    OrientationReport,
)

logger = logging.getLogger(__name__)


class ImageOrientationError(RuntimeError):
    """Изображение не может быть декодировано, или невозможно определить его ориентацию."""


class OrientationDetector(ABC):
    @abstractmethod
    def predict(self, image: Image.Image) -> OrientationPrediction:
        """Предсказывает корректирующий поворот для RGB-изображения, уже транспонированного по EXIF."""
        raise NotImplementedError


class OrientationPolicy(ABC):
    @abstractmethod
    def decide(
        self, image: Image.Image, detector: OrientationDetector, min_confidence: float
    ) -> OrientationDecision:
        raise NotImplementedError


class ImageNormalizationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    image: bytes
    report: OrientationReport


class ImageOrientationNormalizer:
    def __init__(
        self,
        detector: OrientationDetector,
        *,
        min_confidence: float,
        max_input_bytes: int,
        max_pixels: int,
        apply_model_rotation: bool = True,
        policy: OrientationPolicy | None = None,
    ) -> None:
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if max_input_bytes <= 0 or max_pixels <= 0:
            raise ValueError("Image limits must be positive")
        self.detector = detector
        self.min_confidence = min_confidence
        self.max_input_bytes = max_input_bytes
        self.max_pixels = max_pixels
        self.apply_model_rotation = apply_model_rotation
        self.policy = policy

    def normalize(self, data: bytes) -> bytes:
        return self.normalize_with_report(data).image

    def normalize_with_report(self, data: bytes) -> ImageNormalizationResult:
        image, exif_corrected = self.decode(data)
        try:
            if self.policy is not None:
                decision = self.policy.decide(image, self.detector, self.min_confidence)
            else:
                prediction = self.detector.predict(image)
                accepted = prediction.confidence >= self.min_confidence
                decision = OrientationDecision(
                    accepted=accepted,
                    correction_angle=prediction.correction_angle if accepted else None,
                    reason="single_prediction" if accepted else "low_confidence",
                    votes=(prediction,),
                )
            angle = (
                decision.correction_angle
                if self.apply_model_rotation and decision.accepted
                else 0
            )
            needs_review = not decision.accepted or angle != decision.correction_angle
            review_reason = (
                decision.reason
                if not decision.accepted
                else "model_rotation_disabled"
                if needs_review
                else None
            )
            rotations = {
                90: Image.Transpose.ROTATE_90,
                180: Image.Transpose.ROTATE_180,
                270: Image.Transpose.ROTATE_270,
            }
            if angle:
                rotated = image.transpose(rotations[angle])
                image.close()
                image = rotated
            image.info.clear()
            with BytesIO() as output:
                image.save(output, format="PNG")
                result = output.getvalue()
            logger.info(
                "Image orientation normalized exif_corrected=%s predicted_angle=%s "
                "applied_angle=%s decision_reason=%s needs_review=%s "
                "review_reason=%s votes=%s width=%s height=%s model_rotation_enabled=%s",
                exif_corrected,
                decision.correction_angle,
                angle,
                decision.reason,
                needs_review,
                review_reason,
                [
                    (vote.correction_angle, round(vote.confidence, 4))
                    for vote in decision.votes
                ],
                image.width,
                image.height,
                self.apply_model_rotation,
            )
            return ImageNormalizationResult(
                image=result,
                report=OrientationReport(
                    exif_corrected=exif_corrected,
                    decision=decision,
                    model_rotation_enabled=self.apply_model_rotation,
                    applied_angle=angle,
                    needs_review=needs_review,
                    review_reason=review_reason,
                ),
            )
        finally:
            image.close()

    def decode(self, data: bytes) -> tuple[Image.Image, bool]:
        """
        Декодирует и применяет EXIF.
        Возвращенное изображение в формате RGB принадлежит вызывающей стороне.
        """
        if not data or len(data) > self.max_input_bytes:
            raise ImageOrientationError("Empty image or input size limit exceeded")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as source:
                    if source.width * source.height > self.max_pixels:
                        raise ImageOrientationError("Image exceeds pixel limit")
                    if getattr(source, "n_frames", 1) != 1:
                        raise ImageOrientationError(
                            "Multi-frame images are not supported"
                        )
                    exif_corrected = source.getexif().get(274, 1) in {
                        2,
                        3,
                        4,
                        5,
                        6,
                        7,
                        8,
                    }
                    with ImageOps.exif_transpose(source) as oriented:
                        oriented.load()
                        if (
                            "A" in oriented.getbands()
                            or "transparency" in oriented.info
                        ):
                            with oriented.convert("RGBA") as rgba:
                                image = Image.new("RGB", rgba.size, "white")
                                with rgba.getchannel("A") as alpha:
                                    image.paste(rgba, mask=alpha)
                        else:
                            image = oriented.convert("RGB")
                        image.info.clear()
                        return image, exif_corrected
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            raise ImageOrientationError("Could not decode image") from error
