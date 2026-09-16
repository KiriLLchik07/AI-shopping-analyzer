from abc import ABC, abstractmethod

from backend.app.schemas.processing import (
    ReceiptProcessingInput,
    ReceiptProcessingResult,
)


class ReceiptPipeline(ABC):
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
    def preprocess(self, source: ReceiptProcessingInput) -> bytes:
        raise NotImplementedError("Receipt image preprocessing is not implemented yet")

    def recognize(self, image: bytes) -> str:
        raise NotImplementedError("Receipt OCR is not implemented yet")

    def parse(self, raw_text: str) -> ReceiptProcessingResult:
        raise NotImplementedError("Receipt parsing is not implemented yet")


def get_receipt_pipeline() -> ReceiptPipeline:
    return UnconfiguredReceiptPipeline()
