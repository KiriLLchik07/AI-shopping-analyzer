from functools import lru_cache

from backend.app.core.config import image_settings, ocr_settings
from backend.app.ocr.interface import OcrProvider
from backend.app.ocr.paddle_provider import PaddleOcrProvider


@lru_cache
def get_ocr_provider() -> OcrProvider:
    return PaddleOcrProvider(
        config=ocr_settings,
        max_pixels=image_settings.max_pixels,
    )
