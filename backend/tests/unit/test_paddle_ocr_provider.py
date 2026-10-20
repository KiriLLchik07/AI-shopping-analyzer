from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from backend.app.core.config import OcrSettings
from backend.app.ocr.exceptions import OcrConfigurationError, OcrRecognitionError
from backend.app.ocr.paddle_provider import PaddleOcrProvider


def png():
    with Image.new("RGB", (4, 3), (255, 20, 10)) as image, BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


@pytest.fixture
def configured(tmp_path):
    pytest.importorskip("numpy")
    for name in ("PP-OCRv5_mobile_det", "cyrillic_PP-OCRv5_mobile_rec"):
        folder = tmp_path / name
        folder.mkdir()
        for filename in ("inference.json", "inference.pdiparams", "inference.yml"):
            (folder / filename).write_bytes(b"test")
    engine = Mock()
    engine.predict.return_value = [
        {"rec_texts": ["МОЛОКО", "ИТОГ 100.00"], "rec_scores": [0.8, 1.0]}
    ]
    factory = Mock(return_value=engine)
    provider = PaddleOcrProvider(
        config=OcrSettings(model_dir=tmp_path, _env_file=None),
        engine_factory=factory,
    )
    return provider, engine, factory


def test_cyrillic_result_bgr_and_lazy_model_reuse(configured):
    provider, engine, factory = configured
    factory.assert_not_called()
    result = provider.recognize(png())
    assert result.raw_text == "МОЛОКО\nИТОГ 100.00"
    assert result.confidence == pytest.approx(0.9)
    assert [(part.text, part.confidence) for part in result.fragments] == [
        ("МОЛОКО", 0.8),
        ("ИТОГ 100.00", 1.0),
    ]
    assert engine.predict.call_args.kwargs["input"][0, 0].tolist() == [10, 20, 255]
    provider.recognize(png())
    factory.assert_called_once()
    args = factory.call_args.kwargs
    assert args["device"] == "cpu"
    assert args["use_doc_orientation_classify"] is False
    assert args["use_doc_unwarping"] is False
    assert args["use_textline_orientation"] is False
    assert args["text_recognition_model_dir"].endswith("cyrillic_PP-OCRv5_mobile_rec")


def test_missing_models_fail_before_sdk_is_created(tmp_path):
    factory = Mock()
    with pytest.raises(OcrConfigurationError):
        PaddleOcrProvider(
            config=OcrSettings(model_dir=tmp_path, _env_file=None),
            engine_factory=factory,
        ).recognize(png())
    factory.assert_not_called()


def test_provider_uses_model_names_and_files_from_config(configured):
    provider, _, factory = configured
    config = provider.config
    (config.model_dir / config.detection_model_name).rename(
        config.model_dir / "custom-detector"
    )
    (config.model_dir / config.recognition_model_name).rename(
        config.model_dir / "custom-recognizer"
    )
    provider.config = config.model_copy(
        update={
            "detection_model_name": "custom-detector",
            "recognition_model_name": "custom-recognizer",
            "model_files": (*config.model_files, "metadata.json"),
        }
    )
    with pytest.raises(OcrConfigurationError):
        provider.load()
    factory.assert_not_called()
    for name in ("custom-detector", "custom-recognizer"):
        (config.model_dir / name / "metadata.json").write_text("{}")
    provider.load()
    assert factory.call_args.kwargs["text_detection_model_name"] == "custom-detector"
    assert factory.call_args.kwargs["text_recognition_model_dir"] == str(
        config.model_dir / "custom-recognizer"
    )


def test_corrupt_image_never_loads_model(configured):
    provider, _, factory = configured
    with pytest.raises(OcrRecognitionError):
        provider.recognize(b"not an image")
    factory.assert_not_called()


def test_oversized_image_never_loads_model(configured):
    provider, _, factory = configured
    provider.max_pixels = 10
    with pytest.raises(OcrRecognitionError):
        provider.recognize(png())
    factory.assert_not_called()


def test_no_text_has_no_confidence(configured):
    provider, engine, _ = configured
    engine.predict.return_value = [{"rec_texts": [], "rec_scores": []}]
    result = provider.recognize(png())
    assert result.raw_text == "" and result.confidence is None
    assert result.fragments == ()


def test_provider_preserves_scores_after_filtering_blank_and_multiline_fragments(
    configured,
):
    provider, engine, _ = configured
    engine.predict.return_value = [
        {
            "rec_texts": [" ", "  Молоко\n100.00*1шт=100.00  ", "ИТОГ 100.00"],
            "rec_scores": [0.01, 0.8, 0.9],
        }
    ]
    result = provider.recognize(png())
    assert result.raw_text == "Молоко\n100.00*1шт=100.00\nИТОГ 100.00"
    assert len(result.fragments) == 2
    assert result.fragments[0].confidence == 0.8
    assert result.fragments[0].text == "Молоко\n100.00*1шт=100.00"
    assert result.confidence == pytest.approx(0.85)


@pytest.mark.parametrize(
    "output",
    [
        [],
        [{"rec_texts": ["a"], "rec_scores": []}],
        [{"rec_texts": ["a"], "rec_scores": [float("nan")]}],
        [{"rec_texts": ["a"], "rec_scores": [1.2]}],
        [{"rec_texts": [1], "rec_scores": [0.8]}],
        [{}, {}],
        [{}],
    ],
)
def test_malformed_sdk_output_is_recognition_failure(configured, output):
    provider, engine, _ = configured
    engine.predict.return_value = output
    with pytest.raises(OcrRecognitionError):
        provider.recognize(png())


def test_sdk_failure_preserves_cause_but_not_private_details_in_message(configured):
    provider, engine, _ = configured
    engine.predict.side_effect = RuntimeError("private SDK details")
    with pytest.raises(OcrRecognitionError) as error:
        provider.recognize(png())
    assert "private" not in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
