from abc import ABC, abstractmethod

from backend.app.core.config import image_settings
from backend.app.image_processing.factory import get_image_orientation_normalizer
from backend.app.image_processing.orientation import ImageOrientationNormalizer
from backend.app.ocr.exceptions import OcrConfigurationError
from backend.app.ocr.factory import get_ocr_provider
from backend.app.ocr.interface import OcrProvider
from backend.app.schemas.ocr import OcrResult
from backend.app.schemas.processing import (
    ReceiptPreprocessingResult,
    ReceiptProcessingInput,
    ReceiptProcessingResult,
)
from backend.app.storage.factory import get_object_storage
from backend.app.storage.interface import ObjectStorage


class ReceiptPipeline(ABC):
    def recognize_with_metadata(self, image: bytes) -> OcrResult:
        return OcrResult(raw_text=self.recognize(image))

    def preprocess_with_metadata(
        self, source: ReceiptProcessingInput
    ) -> ReceiptPreprocessingResult:
        return ReceiptPreprocessingResult(image=self.preprocess(source))

    @abstractmethod
    def preprocess(self, source: ReceiptProcessingInput) -> bytes:
        pass

    @abstractmethod
    def recognize(self, image: bytes) -> str:
        pass

    @abstractmethod
    def parse(self, raw_text: str) -> ReceiptProcessingResult:
        pass


class UnconfiguredReceiptPipeline(ReceiptPipeline):
    def __init__(
        self,
        object_storage: ObjectStorage,
        orientation_normalizer: ImageOrientationNormalizer,
        ocr_provider: OcrProvider | None = None,
    ) -> None:
        self.object_storage = object_storage
        self.orientation_normalizer = orientation_normalizer
        self.ocr_provider = ocr_provider

    def preprocess(self, source: ReceiptProcessingInput) -> bytes:
        return self.preprocess_with_metadata(source).image

    def preprocess_with_metadata(
        self, source: ReceiptProcessingInput
    ) -> ReceiptPreprocessingResult:
        original = self.object_storage.download(
            source.image_object_key, max_bytes=image_settings.max_upload_bytes
        )
        result = self.orientation_normalizer.normalize_with_report(original)
        return ReceiptPreprocessingResult(
            image=result.image, orientation_report=result.report
        )

    def recognize(self, image: bytes) -> str:
        return self.recognize_with_metadata(image).raw_text

    def recognize_with_metadata(self, image: bytes) -> OcrResult:
        if self.ocr_provider is None:
            raise OcrConfigurationError("OCR provider is not configured")
        return self.ocr_provider.recognize(image)

    def parse(self, raw_text: str) -> ReceiptProcessingResult:
        raise NotImplementedError("Receipt parsing is not implemented yet")


def get_receipt_pipeline() -> ReceiptPipeline:
    return UnconfiguredReceiptPipeline(
        object_storage=get_object_storage(),
        orientation_normalizer=get_image_orientation_normalizer(),
        ocr_provider=get_ocr_provider(),
    )
