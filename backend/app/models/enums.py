from enum import StrEnum


class ReceiptReviewStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"


class ProcessingStatus(StrEnum):
    PENDING_DISPATCH = "pending_dispatch"
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    OCR_PROCESSING = "ocr_processing"
    PARSING = "parsing"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


RUNNING_PROCESSING_STATUSES = {
    ProcessingStatus.PREPROCESSING,
    ProcessingStatus.OCR_PROCESSING,
    ProcessingStatus.PARSING,
}

ACTIVE_PROCESSING_STATUSES = RUNNING_PROCESSING_STATUSES | {
    ProcessingStatus.PENDING_DISPATCH,
    ProcessingStatus.QUEUED,
    ProcessingStatus.RETRY_SCHEDULED,
}

MAX_MANUAL_OCR_RUNS = 3
