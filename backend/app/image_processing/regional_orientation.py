from PIL import Image

from backend.app.image_processing.orientation import (
    OrientationDetector,
    OrientationPolicy,
)
from backend.app.schemas.orientation import OrientationDecision, OrientationPrediction


def region_boxes(size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    width, height = size
    if min(width, height) < 1:
        raise ValueError("Image dimensions must be positive")
    side = max(1, min(width, height) // 2)
    starts = [round(index * (max(width, height) - side) / 4) for index in range(5)]
    if width >= height:
        top = (height - side) // 2
        boxes = [(start, top, start + side, top + side) for start in starts]
    else:
        left = (width - side) // 2
        boxes = [(left, start, left + side, start + side) for start in starts]
    return list(dict.fromkeys(boxes))


def decide_votes(
    votes: tuple[OrientationPrediction, ...], threshold: float
) -> OrientationDecision:
    confident = [vote for vote in votes if vote.confidence >= threshold]
    angles = {vote.correction_angle for vote in confident}
    if len(angles) > 1:
        return OrientationDecision(
            accepted=False,
            correction_angle=None,
            reason="confident_disagreement",
            votes=votes,
        )
    if len(confident) < 3:
        return OrientationDecision(
            accepted=False,
            correction_angle=None,
            reason="insufficient_confident_votes",
            votes=votes,
        )
    return OrientationDecision(
        accepted=True,
        correction_angle=confident[0].correction_angle,
        reason="consensus",
        votes=votes,
    )


class RegionalOrientationPolicy(OrientationPolicy):
    def decide(
        self, image: Image.Image, detector: OrientationDetector, min_confidence: float
    ) -> OrientationDecision:
        votes = []
        for box in region_boxes(image.size):
            with image.crop(box) as patch:
                votes.append(detector.predict(patch))
        return decide_votes(tuple(votes), min_confidence)
