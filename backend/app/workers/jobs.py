import logging
from uuid import UUID

from rq import get_current_job

from backend.app.db.session import SessionLocal
from backend.app.models.enums import ReceiptStatus
from backend.app.services.receipt_pipeline import get_receipt_pipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
)

logger = logging.getLogger(__name__)


def process_receipt(receipt_id: str) -> None:
    parsed_receipt_id = UUID(receipt_id)

    job = get_current_job()
    job_id = job.id if job else "manual"

    service = ReceiptProcessingService(SessionLocal)

    source = service.start_processing(parsed_receipt_id)

    if source is None:
        logger.info(
            "Receipt job skipped: receipt missing, active or finished "
            "receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )
        return

    try:
        pipeline = get_receipt_pipeline()
        logger.info(
            "Receipt job started receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )

        image = pipeline.preprocess(source)

        if not service.advance_status(
            receipt_id=parsed_receipt_id,
            expected_status=ReceiptStatus.PREPROCESSING,
            new_status=ReceiptStatus.OCR_PROCESSING,
        ):
            logger.info(
                "Receipt job stopped before OCR: state changed receipt_id=%s job_id=%s",
                receipt_id,
                job_id,
            )
            return

        logger.info(
            "Receipt OCR started receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )

        raw_text = pipeline.recognize(image)

        if not service.advance_status(
            receipt_id=parsed_receipt_id,
            expected_status=ReceiptStatus.OCR_PROCESSING,
            new_status=ReceiptStatus.PARSING,
        ):
            logger.info(
                "Receipt job stopped before parsing: state changed "
                "receipt_id=%s job_id=%s",
                receipt_id,
                job_id,
            )
            return

        logger.info(
            "Receipt parsing started receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )

        result = pipeline.parse(raw_text)

        result = result.model_copy(
            update={"raw_ocr_text": raw_text},
        )

        outcome = service.save_result(receipt_id=parsed_receipt_id, result=result)

        logger.info(
            "Receipt job finished receipt_id=%s job_id=%s outcome=%s",
            receipt_id,
            job_id,
            outcome.value,
        )
    except Exception as error:
        logger.exception(
            "Receipt processing failed receipt_id=%s job_id=%s",
            receipt_id,
            job_id,
        )

        try:
            service.mark_failed(parsed_receipt_id, error=error)
        except Exception:
            logger.exception(
                "Could not persist receipt processing error receipt_id=%s job_id=%s",
                receipt_id,
                job_id,
            )
        raise
