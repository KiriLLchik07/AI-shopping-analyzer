from unittest.mock import Mock

import pytest

from backend.app.core.receipt_processing_errors import get_safe_processing_error
from backend.app.ocr.exceptions import OcrConfigurationError, OcrRecognitionError
from backend.app.schemas.ocr import OcrResult
from backend.app.services.receipt_pipeline import (
    UnconfiguredReceiptPipeline,
    get_receipt_pipeline,
)


def test_pipeline_delegates_to_provider_and_keeps_metadata():
    provider = Mock()
    provider.recognize.return_value = OcrResult(
        raw_text="МОЛОКО\n100.00", confidence=0.9
    )
    pipeline = UnconfiguredReceiptPipeline(Mock(), Mock(), provider)
    assert pipeline.recognize(b"image") == "МОЛОКО\n100.00"
    assert pipeline.recognize_with_metadata(b"image").confidence == 0.9
    provider.recognize.assert_called_with(b"image")


def test_production_factory_connects_provider_without_loading_sdk(monkeypatch):
    from backend.app.services import receipt_pipeline

    provider = Mock()
    monkeypatch.setattr(receipt_pipeline, "get_ocr_provider", lambda: provider)
    monkeypatch.setattr(receipt_pipeline, "get_object_storage", Mock)
    monkeypatch.setattr(receipt_pipeline, "get_image_orientation_normalizer", Mock)
    assert get_receipt_pipeline().ocr_provider is provider


@pytest.mark.parametrize("error_type", [OcrConfigurationError, OcrRecognitionError])
def test_pipeline_propagates_typed_error_and_safe_message(error_type):
    provider = Mock()
    provider.recognize.side_effect = error_type("PRIVATE SDK traceback")
    with pytest.raises(error_type) as caught:
        UnconfiguredReceiptPipeline(Mock(), Mock(), provider).recognize(b"image")
    assert "PRIVATE" not in get_safe_processing_error(caught.value).message
