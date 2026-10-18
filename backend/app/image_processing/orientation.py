import logging
import warnings
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ImageOrientationError(RuntimeError):
    """Изображение не может быть декодировано, или невозможно определить его ориентацию."""


class OrientationPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    correction_angle: Literal[0, 90, 180, 270]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class OrientationDetector(ABC):
    @abstractmethod
    def predict(self, image: Image.Image) -> OrientationPrediction:
        """Предсказывает корректирующий поворот для RGB-изображения, уже транспонированного по EXIF."""
        raise NotImplementedError


class ImageOrientationNormalizer:
    def __init__(
        self,
        detector: OrientationDetector,
        *,
        min_confidence: float,
        max_input_bytes: int,
        max_pixels: int,
        apply_model_rotation: bool = True,
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

    def normalize(self, data: bytes) -> bytes:
        image, exif_corrected = self.decode(data)
        try:
            prediction = self.detector.predict(image)
            angle = (
                prediction.correction_angle
                if self.apply_model_rotation
                and prediction.confidence >= self.min_confidence
                else 0
            )
            if self.apply_model_rotation and prediction.correction_angle and angle == 0:
                logger.warning(
                    "Image rotation skipped confidence=%.4f threshold=%.4f",
                    prediction.confidence,
                    self.min_confidence,
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
                "applied_angle=%s confidence=%.4f width=%s height=%s model_rotation_enabled=%s",
                exif_corrected,
                prediction.correction_angle,
                angle,
                prediction.confidence,
                image.width,
                image.height,
                self.apply_model_rotation,
            )
            return result
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
