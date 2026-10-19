from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image, ImageChops

from backend.app.image_processing.orientation import (
    ImageOrientationError,
    ImageOrientationNormalizer,
    OrientationPrediction,
)
from backend.app.image_processing.regional_orientation import (
    RegionalOrientationPolicy,
    region_boxes,
)


def make_normalizer(angles, confidences=None, enabled=True):
    detector = Mock()
    detector.predict.side_effect = [
        OrientationPrediction(correction_angle=angle, confidence=confidence)
        for angle, confidence in zip(
            angles, confidences or [0.9] * len(angles), strict=True
        )
    ]
    return ImageOrientationNormalizer(
        detector,
        min_confidence=0.8,
        max_input_bytes=100_000,
        max_pixels=10_000,
        apply_model_rotation=enabled,
        policy=RegionalOrientationPolicy(),
    )


def image_bytes():
    with Image.new("RGB", (20, 40), "white") as image, BytesIO() as buffer:
        image.putpixel((0, 0), (255, 0, 0))
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def test_regional_rotation_preserves_exact_pixels_and_reports_applied_angle():
    source = image_bytes()
    normalizer = make_normalizer([90] * 5)
    result = normalizer.normalize_with_report(source)
    with (
        Image.open(BytesIO(source)) as original,
        original.transpose(Image.Transpose.ROTATE_90) as expected,
        Image.open(BytesIO(result.image)) as actual,
    ):
        assert ImageChops.difference(actual, expected).getbbox() is None
    assert result.report.applied_angle == 90
    assert not result.report.needs_review
    assert result.report.decision.accepted
    assert len(result.report.decision.votes) == 5
    assert normalizer.detector.predict.call_count == 5


def test_conflict_keeps_pixels_and_requires_review(caplog):
    normalizer = make_normalizer([180, 180, 180, 180, 0])
    source = image_bytes()
    with caplog.at_level("INFO"):
        result = normalizer.normalize_with_report(source)
    assert result.report.needs_review
    assert result.report.review_reason == "confident_disagreement"
    assert result.report.applied_angle == 0
    with (
        Image.open(BytesIO(source)) as original,
        Image.open(BytesIO(result.image)) as actual,
    ):
        assert ImageChops.difference(actual, original).getbbox() is None
    assert "needs_review=True" in caplog.text
    assert "confident_disagreement" in caplog.text


def test_observation_mode_does_not_claim_unapplied_rotation_succeeded():
    result = make_normalizer([90] * 5, enabled=False).normalize_with_report(
        image_bytes()
    )
    assert result.report.decision.correction_angle == 90
    assert result.report.applied_angle == 0
    assert result.report.needs_review
    assert result.report.review_reason == "model_rotation_disabled"


def test_confident_zero_is_a_decision_not_an_abstention():
    result = make_normalizer([0] * 5).normalize_with_report(image_bytes())
    assert result.report.decision.accepted
    assert not result.report.needs_review


def test_only_two_confident_regions_require_review():
    result = make_normalizer([90] * 5, [0.9, 0.9, 0.7, 0.7, 0.7]).normalize_with_report(
        image_bytes()
    )
    assert result.report.needs_review
    assert result.report.review_reason == "insufficient_confident_votes"


def test_model_failure_is_not_disguised_as_an_uncertain_prediction():
    normalizer = make_normalizer([90] * 5)
    normalizer.detector.predict.side_effect = ImageOrientationError("Model unavailable")
    with pytest.raises(ImageOrientationError):
        normalizer.normalize_with_report(image_bytes())


def test_regions_are_taken_after_exif_correction():
    normalizer = make_normalizer([0] * 5)
    with (
        Image.open(BytesIO(image_bytes())) as original,
        original.transpose(Image.Transpose.ROTATE_270) as expected,
        BytesIO() as buffer,
    ):
        metadata = Image.Exif()
        metadata[274] = 6
        original.save(buffer, format="PNG", exif=metadata)
        boxes = iter(region_boxes(expected.size))

        def detect(patch):
            with expected.crop(next(boxes)) as correct_patch:
                assert patch.size == correct_patch.size
                assert ImageChops.difference(patch, correct_patch).getbbox() is None
            return OrientationPrediction(correction_angle=0, confidence=0.9)

        normalizer.detector.predict.side_effect = detect
        result = normalizer.normalize_with_report(buffer.getvalue())
        assert result.report.exif_corrected
        with Image.open(BytesIO(result.image)) as actual:
            assert 274 not in actual.getexif()
            assert ImageChops.difference(actual, expected).getbbox() is None


def test_tiny_image_does_not_duplicate_one_region_into_a_consensus():
    with Image.new("RGB", (1, 1), "white") as image, BytesIO() as buffer:
        image.save(buffer, format="PNG")
        normalizer = make_normalizer([0])
        result = normalizer.normalize_with_report(buffer.getvalue())
    assert normalizer.detector.predict.call_count == 1
    assert result.report.needs_review
    assert result.report.review_reason == "insufficient_confident_votes"
