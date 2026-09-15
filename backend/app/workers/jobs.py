import logging
from uuid import UUID

from rq import get_current_job

from backend.app.db.session import SessionLocal
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingInput,
    ReceiptProcessingService,
)

logger = logging.getLogger(__name__)


def build_receipt_result(source: ReceiptProcessingInput) -> ReceiptProcessingResult:
    # Здесь будет подключаться OCR pipeline

    raise NotImplementedError("Receipt OCR pipeline is not implemented yet")


def process_receipt(receipt_id: str) -> None:
    parsed_receipt_id = UUID(receipt_id)

    job = get_current_job()
    job_id = job.id if job else "manual"

    service = ReceiptProcessingService(SessionLocal)

    logger.info(
        "Receipt job started receipt_id=%s job_id=%s",
        receipt_id,
        job_id,
    )

    source = service.get_pending_input(parsed_receipt_id)

    if source is None:
        logger.info(
            "Receipt job skipped: receipt deleted or result already saved "
            "receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )
        return

    result = build_receipt_result(source=source)
    outcome = service.save_result(receipt_id=parsed_receipt_id, result=result)

    logger.info(
        "Receipt job finished receipt_id=%s job_id=%s outcome=%s",
        receipt_id,
        job_id,
        outcome.value,
    )
