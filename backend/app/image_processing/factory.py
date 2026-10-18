from functools import lru_cache

from backend.app.core.config import image_settings
from backend.app.image_processing.orientation import ImageOrientationNormalizer
from backend.app.image_processing.paddle_orientation import PaddleOrientationDetector


@lru_cache(maxsize=1)
def get_image_orientation_normalizer() -> ImageOrientationNormalizer:
    return ImageOrientationNormalizer(
        detector=PaddleOrientationDetector(
            model_dir=image_settings.orientation_model_dir,
            device=image_settings.orientation_device,
            cpu_threads=image_settings.orientation_cpu_threads,
        ),
        min_confidence=image_settings.orientation_min_confidence,
        max_input_bytes=image_settings.max_upload_bytes,
        max_pixels=image_settings.max_pixels,
        apply_model_rotation=image_settings.orientation_apply_model_rotation,
    )
