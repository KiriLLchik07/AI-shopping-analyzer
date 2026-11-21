from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import setting
from backend.app.core.exceptions import (
    ConflictError,
    ReceiptNotFoundError,
    ReceiptProcessingConflictError,
)
from backend.app.core.logging import get_correlation_id, normalize_correlation_id
from backend.app.core.receipt_processing_errors import get_safe_processing_error
from backend.app.models.enums import (
    RUNNING_PROCESSING_STATUSES,
    ProcessingStatus,
    ReceiptReviewStatus,
)
from backend.app.models.receipt import Receipt
from backend.app.repositories.receipt_processing_repository import (
    ReceiptProcessingRepository,
)
from backend.app.schemas.ocr import OcrResult
from backend.app.schemas.orientation import OrientationReport
from backend.app.schemas.processing import (
    ReceiptProcessingInput,
    ReceiptProcessingResult,
    ReceiptProcessTicket,
)
from backend.app.services.receipt_categorization_service import (
    ReceiptCategorizationService,
)

PROCESSING_TIMEOUT_SECONDS = 300
RECOVERY_GRACE_SECONDS = 60


def record_processing_failure(
    receipt: Receipt, error: BaseException | None, *, retryable: bool
) -> None:
    safe_error = get_safe_processing_error(
        error if isinstance(error, Exception) else None
    )
    receipt.processing_error_code = safe_error.code
    receipt.processing_error_message = safe_error.message

    delays = setting.receipt_retry_intervals_seconds
    used = receipt.automatic_ocr_retries
    if retryable and used < len(delays):
        receipt.automatic_ocr_retries += 1
        receipt.processing_version += 1
        receipt.processing_status = ProcessingStatus.RETRY_SCHEDULED
        receipt.ocr_due_at = datetime.now(UTC) + timedelta(seconds=delays[used])
    else:
        receipt.processing_status = ProcessingStatus.FAILED
        receipt.ocr_due_at = None


class SaveProcessingOutcome(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    RECEIPT_DELETED = "receipt_deleted"
    STALE_JOB = "stale_job"


class ReceiptProcessingService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def prepare_process(
        self, receipt_id: UUID, user_id: UUID, replace_items: bool
    ) -> ReceiptProcessTicket:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id, user_id)

            if receipt is None:
                raise ReceiptNotFoundError

            if (
                receipt.receipt_status != ReceiptReviewStatus.DRAFT
                or receipt.processing_status != ProcessingStatus.FAILED
            ):
                raise ConflictError(
                    "Повтор доступен только после окончательного сбоя обработки."
                )
            if receipt.manual_ocr_attempts_remaining == 0:
                raise ConflictError(
                    "Все ручные попытки использованы. Заполните чек вручную."
                )

            if repository.has_items(receipt_id=receipt_id) and not replace_items:
                raise ConflictError(
                    "В чеке уже есть товары. Для их замены передайте replace_items=true."
                )

            repository.prepare_process(receipt=receipt, replace_items=replace_items)
            receipt.manual_ocr_runs += 1
            receipt.ocr_due_at = datetime.now(UTC)
            receipt.ocr_correlation_id = normalize_correlation_id(get_correlation_id())

            ticket = ReceiptProcessTicket(
                receipt_id=receipt.receipt_id,
                processing_version=receipt.processing_version,
            )

        return ticket

    def start_processing(
        self, receipt_id: UUID, processing_version: int = 1
    ) -> ReceiptProcessingInput | None:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return

            if receipt.processing_version != processing_version:
                return

            if receipt.processing_result_saved_at is not None:
                return

            if receipt.processing_status not in {
                ProcessingStatus.PENDING_DISPATCH,
                ProcessingStatus.QUEUED,
                ProcessingStatus.RETRY_SCHEDULED,
            }:
                return

            source = ReceiptProcessingInput(
                receipt_id=receipt.receipt_id, image_object_key=receipt.image_object_key
            )

            repository.set_status(
                receipt,
                ProcessingStatus.PREPROCESSING,
                clear_error=True,
                clear_orientation_report=True,
                clear_ocr_result=True,
            )

            receipt.ocr_due_at = datetime.now(UTC) + timedelta(
                seconds=PROCESSING_TIMEOUT_SECONDS + RECOVERY_GRACE_SECONDS
            )

        return source

    def advance_status(
        self,
        receipt_id: UUID,
        expected_status: ProcessingStatus,
        new_status: ProcessingStatus,
        processing_version: int = 1,
        orientation_report: OrientationReport | None = None,
    ) -> bool:

        allowed_transitions = {
            (ProcessingStatus.PREPROCESSING, ProcessingStatus.OCR_PROCESSING),
            (ProcessingStatus.OCR_PROCESSING, ProcessingStatus.PARSING),
        }

        if (expected_status, new_status) not in allowed_transitions:
            raise ValueError(
                f"Unsupported processing transition: "
                f"{expected_status.value} -> {new_status.value}"
            )

        if (
            orientation_report is not None
            and expected_status != ProcessingStatus.PREPROCESSING
        ):
            raise ValueError("Orientation report can only be saved after preprocessing")

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return False

            if receipt.processing_version != processing_version:
                return False

            if receipt.processing_result_saved_at is not None:
                return False

            if receipt.processing_status != expected_status:
                return False

            repository.set_status(
                receipt, new_status, orientation_report=orientation_report
            )

        return True

    def save_ocr_result(
        self,
        receipt_id: UUID,
        result: OcrResult,
        processing_version: int = 1,
    ) -> bool:
        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)
            if receipt is None:
                return False
            if receipt.processing_version != processing_version:
                return False
            if receipt.processing_result_saved_at is not None:
                return False
            if receipt.processing_status != ProcessingStatus.OCR_PROCESSING:
                return False
            repository.store_ocr_result(receipt, result)
        return True

    def mark_failed(
        self,
        receipt_id: UUID,
        error: BaseException | None = None,
        processing_version: int = 1,
        *,
        retryable: bool = False,
    ) -> bool:
        with self.session_factory.begin() as session:
            receipt = ReceiptProcessingRepository(session).get_for_update(receipt_id)
            if (
                receipt is None
                or receipt.processing_version != processing_version
                or receipt.processing_status not in RUNNING_PROCESSING_STATUSES
            ):
                return False

            record_processing_failure(receipt, error, retryable=retryable)
            return True

    def save_result(
        self,
        receipt_id: UUID,
        result: ReceiptProcessingResult,
        processing_version: int = 1,
    ) -> SaveProcessingOutcome:

        with self.session_factory.begin() as session:
            repository = ReceiptProcessingRepository(session)
            receipt = repository.get_for_update(receipt_id)

            if receipt is None:
                return SaveProcessingOutcome.RECEIPT_DELETED

            if receipt.processing_version != processing_version:
                return SaveProcessingOutcome.STALE_JOB

            if receipt.processing_result_saved_at is not None:
                return SaveProcessingOutcome.ALREADY_SAVED

            if receipt.processing_status != ProcessingStatus.PARSING:
                return SaveProcessingOutcome.STALE_JOB

            if receipt.items_revision != receipt.processing_items_revision:
                raise ReceiptProcessingConflictError()

            if (
                repository.has_items(receipt_id)
                and not receipt.processing_replace_items
            ):
                raise ReceiptProcessingConflictError()

            repository.store_result(
                receipt=receipt,
                items=ReceiptCategorizationService(session).suggest_items(result.items),
                raw_ocr_text=result.raw_ocr_text,
                parsed_receipt=result.parsed_receipt,
                saved_at=datetime.now(UTC),
            )

        return SaveProcessingOutcome.SAVED
