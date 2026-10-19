from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import EndpointConnectionError
from PIL import Image, ImageChops

from backend.app.image_processing.orientation import (
    ImageNormalizationResult,
    ImageOrientationError,
    ImageOrientationNormalizer,
    OrientationPrediction,
)
from backend.app.schemas.orientation import OrientationDecision, OrientationReport
from backend.app.schemas.processing import ReceiptProcessingInput
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline
from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.s3_storage import S3ObjectStorage


def encode(image, **kwargs):
    with BytesIO() as output:
        image.save(output, format="PNG", **kwargs)
        return output.getvalue()


def normalizer(angle=0, confidence=1):
    detector = Mock()
    detector.predict.return_value = OrientationPrediction(
        correction_angle=angle, confidence=confidence
    )
    return ImageOrientationNormalizer(
        detector, min_confidence=0.8, max_input_bytes=100_000, max_pixels=10_000
    )


@pytest.fixture
def asymmetric_image():
    image = Image.new("RGB", (12, 8), "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((11, 7), (0, 0, 255))
    return image


@pytest.mark.parametrize(
    "angle,operation",
    [
        (0, None),
        (90, Image.Transpose.ROTATE_90),
        (180, Image.Transpose.ROTATE_180),
        (270, Image.Transpose.ROTATE_270),
    ],
)
def test_quadrant_rotation_preserves_pixels(asymmetric_image, angle, operation):
    output = normalizer(angle).normalize(encode(asymmetric_image))
    expected = (
        asymmetric_image.transpose(operation)
        if operation is not None
        else asymmetric_image
    )
    with Image.open(BytesIO(output)) as result:
        assert result.format == "PNG"
        assert result.size == expected.size
        assert ImageChops.difference(result, expected).getbbox() is None


@pytest.mark.parametrize(
    "exif,operation",
    [
        (2, Image.Transpose.FLIP_LEFT_RIGHT),
        (3, Image.Transpose.ROTATE_180),
        (4, Image.Transpose.FLIP_TOP_BOTTOM),
        (5, Image.Transpose.TRANSPOSE),
        (6, Image.Transpose.ROTATE_270),
        (7, Image.Transpose.TRANSVERSE),
        (8, Image.Transpose.ROTATE_90),
    ],
)
def test_exif_is_applied_before_detection_and_removed(
    asymmetric_image, exif, operation
):
    metadata = Image.Exif()
    metadata[274] = exif
    service = normalizer()
    observed = []

    def detect(image):
        expected = asymmetric_image.transpose(operation)
        assert image.size == expected.size
        assert ImageChops.difference(image, expected).getbbox() is None
        observed.append(True)
        return OrientationPrediction(correction_angle=0, confidence=1)

    service.detector.predict.side_effect = detect
    output = service.normalize(encode(asymmetric_image, exif=metadata))
    with Image.open(BytesIO(output)) as result:
        assert 274 not in result.getexif()
    assert observed == [True]


def test_uncertain_prediction_does_not_rotate(asymmetric_image):
    output = normalizer(90, 0.79).normalize(encode(asymmetric_image))
    with Image.open(BytesIO(output)) as result:
        assert ImageChops.difference(result, asymmetric_image).getbbox() is None


def test_observation_mode_preserves_pixels_even_for_confident_prediction(
    asymmetric_image,
):
    service = normalizer(180, 0.99)
    service.apply_model_rotation = False
    with Image.open(BytesIO(service.normalize(encode(asymmetric_image)))) as result:
        assert ImageChops.difference(result, asymmetric_image).getbbox() is None
    service.detector.predict.assert_called_once()


@pytest.mark.parametrize(
    "data",
    [b"", b"invalid image", b"a" * 100_001],
    ids=["empty", "corrupt", "oversized"],
)
def test_invalid_input_does_not_reach_model(data):
    service = normalizer()
    with pytest.raises(ImageOrientationError):
        service.normalize(data)
    service.detector.predict.assert_not_called()


def test_pixel_limit_is_checked_before_inference():
    service = normalizer()
    with pytest.raises(ImageOrientationError):
        service.normalize(encode(Image.new("RGB", (101, 101))))
    service.detector.predict.assert_not_called()


def test_transparency_becomes_white():
    output = normalizer().normalize(encode(Image.new("RGBA", (2, 2))))
    with Image.open(BytesIO(output)) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_pipeline_downloads_then_normalizes():
    storage, service = Mock(), Mock()
    storage.download.return_value = b"original"
    report = OrientationReport(
        exif_corrected=False,
        decision=OrientationDecision(
            accepted=False,
            correction_angle=None,
            reason="confident_disagreement",
            votes=(),
        ),
        model_rotation_enabled=True,
        applied_angle=0,
        needs_review=True,
        review_reason="confident_disagreement",
    )
    service.normalize_with_report.return_value = ImageNormalizationResult(
        image=b"normalized", report=report
    )
    pipeline = UnconfiguredReceiptPipeline(storage, service)
    source = ReceiptProcessingInput(receipt_id=uuid4(), image_object_key="receipt.jpg")
    assert pipeline.preprocess(source) == b"normalized"
    assert storage.download.call_args.args == ("receipt.jpg",)
    service.normalize_with_report.assert_called_once_with(b"original")


@pytest.mark.parametrize("declared_size", [None, 10])
def test_download_enforces_limit_and_closes_stream(declared_size):
    stream = BytesIO(b"0123456789")
    response = {"Body": stream}
    if declared_size is not None:
        response["ContentLength"] = declared_size
    client = Mock()
    client.get_object.return_value = response
    with pytest.raises(ObjectStorageError):
        S3ObjectStorage(client, "test").download("key", max_bytes=5)
    assert stream.closed


def test_download_success_and_network_error():
    client = Mock()
    stream = BytesIO(b"test")
    client.get_object.return_value = {"Body": stream}
    assert S3ObjectStorage(client, "test").download("key", max_bytes=4) == b"test"
    assert stream.closed
    cause = EndpointConnectionError(endpoint_url="http://storage.test")
    client.get_object.side_effect = cause
    with pytest.raises(ObjectStorageError) as failure:
        S3ObjectStorage(client, "test").download("key", max_bytes=4)
    assert failure.value.__cause__ is cause
