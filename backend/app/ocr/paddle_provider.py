import logging
import math
import time
import warnings
from collections.abc import Callable
from io import BytesIO
from itertools import islice
from typing import TYPE_CHECKING, Any

from PIL import Image

from backend.app.ocr.exceptions import OcrConfigurationError, OcrRecognitionError
from backend.app.ocr.interface import OcrProvider
from backend.app.schemas.ocr import OcrFragment, OcrResult

if TYPE_CHECKING:
    from backend.app.core.config import OcrSettings

logger = logging.getLogger(__name__)


class PaddleOcrProvider(OcrProvider):
    """Локальный PP-OCRv5 baseline. Модели повторно используются в рамках вызывающего процесса."""

    def __init__(
        self,
        *,
        config: "OcrSettings",
        max_pixels: int = 20_000_000,
        engine_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.max_pixels = max_pixels
        self._factory = engine_factory
        self._engine: Any = None

    def load(self) -> None:
        if self._engine is not None:
            return
        if not all(
            (self.config.model_dir / model / name).is_file()
            for model in (
                self.config.detection_model_name,
                self.config.recognition_model_name,
            )
            for name in self.config.model_files
        ):
            raise OcrConfigurationError("Local OCR model files are missing")
        try:
            factory = self._factory
            if factory is None:
                from paddleocr import PaddleOCR

                factory = PaddleOCR
            self._engine = factory(
                text_detection_model_name=self.config.detection_model_name,
                text_detection_model_dir=str(
                    self.config.model_dir / self.config.detection_model_name
                ),
                text_recognition_model_name=self.config.recognition_model_name,
                text_recognition_model_dir=str(
                    self.config.model_dir / self.config.recognition_model_name
                ),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=self.config.device,
                cpu_threads=self.config.cpu_threads,
            )
        except Exception as error:
            raise OcrConfigurationError("Could not initialize local OCR") from error

    def recognize(self, image: bytes) -> OcrResult:
        started = time.perf_counter()
        try:
            if len(image) > self.max_pixels * 4 + 1024 * 1024:
                raise ValueError("Encoded image exceeds processing limit")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(image)) as source:
                    if (
                        source.width * source.height > self.max_pixels
                        or getattr(source, "n_frames", 1) != 1
                    ):
                        raise ValueError("Image exceeds processing limits")
                    with source.convert("RGB") as rgb:
                        self.load()
                        import numpy as np

                        bgr = np.ascontiguousarray(
                            np.asarray(rgb, dtype=np.uint8)[:, :, ::-1]
                        )
            results = list(islice(iter(self._engine.predict(input=bgr)), 2))
            if len(results) != 1:
                raise ValueError("Unexpected OCR result count")
            texts, scores = results[0]["rec_texts"], results[0]["rec_scores"]
            if isinstance(texts, (str, bytes)) or len(texts) != len(scores):
                raise ValueError("Invalid OCR fragments")
            retained: list[tuple[str, float]] = []
            for text, score in zip(texts, scores, strict=True):
                score = float(score)
                if (
                    not isinstance(text, str)
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                ):
                    raise ValueError("Invalid OCR fragment")
                if text.strip():
                    retained.append((text.strip(), score))
            result = OcrResult(
                raw_text="\n".join(text for text, _ in retained),
                fragments=tuple(
                    OcrFragment(text=text, confidence=score) for text, score in retained
                ),
                confidence=sum(score for _, score in retained) / len(retained)
                if retained
                else None,
            )
        except OcrConfigurationError:
            raise
        except Exception as error:
            raise OcrRecognitionError("Could not recognize receipt text") from error
        logger.info(
            "Local OCR finished elapsed_seconds=%.3f fragments=%s confidence=%s",
            time.perf_counter() - started,
            len(retained),
            result.confidence,
        )
        return result
