from enum import StrEnum


class ReceiptStatus(StrEnum):
    UPLOADED = "uploaded"
    PREPROCESSING = "preprocessing"
    OCR_PROCESSING = "ocr_processing"
    PARSING = "parsing"
    NEED_REVIEW = "need_review"
    COMPLETED = "completed"
    FAILED = "failed"
