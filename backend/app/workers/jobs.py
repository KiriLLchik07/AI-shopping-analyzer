import logging
from uuid import UUID

from rq import get_current_job

from backend.app.core.logging import (
    get_correlation_id,
    log_context,
    normalize_correlation_id,
)
from backend.app.db.session import SessionLocal
from backend.app.models.enums import ReceiptStatus
from backend.app.services.receipt_pipeline import get_receipt_pipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from backend.app.workers.log_context import get_job_log_context


logger = logging.getLogger(__name__)


def process_receipt(
    receipt_id: str,
    processing_version: int = 1,
) -> None:
    job = get_current_job()

    if job is not None:
        context = get_job_log_context(job)
    else:
        context = {
            "correlation_id": normalize_correlation_id(
                get_correlation_id()
            ),
            "job_id": "manual",
            "receipt_id": receipt_id,
            "processing_version": processing_version,
        }

    with log_context(**context):
        _process_receipt(
            receipt_id=receipt_id,
            processing_version=processing_version,
        )


def _process_receipt(
    receipt_id: str,
    processing_version: int,
) -> None:
    parsed_receipt_id = UUID(receipt_id)
    service = ReceiptProcessingService(SessionLocal)

    logger.info("Receipt job started")

    source = service.start_processing(
        parsed_receipt_id,
        processing_version=processing_version,
    )

    if source is None:
        logger.info(
            "Receipt job skipped: receipt missing, active or finished"
        )
        return

    try:
        pipeline = get_receipt_pipeline()

        logger.info("Receipt preprocessing started")
        image = pipeline.preprocess(source)

        if not service.advance_status(
            receipt_id=parsed_receipt_id,
            expected_status=ReceiptStatus.PREPROCESSING,
            new_status=ReceiptStatus.OCR_PROCESSING,
            processing_version=processing_version,
        ):
            logger.info(
                "Receipt job stopped before OCR: state changed"
            )
            return

        logger.info("Receipt OCR started")
        raw_text = pipeline.recognize(image)

        if not service.advance_status(
            receipt_id=parsed_receipt_id,
            expected_status=ReceiptStatus.OCR_PROCESSING,
            new_status=ReceiptStatus.PARSING,
            processing_version=processing_version,
        ):
            logger.info(
                "Receipt job stopped before parsing: state changed"
            )
            return

        logger.info("Receipt parsing started")
        result = pipeline.parse(raw_text)

        result = result.model_copy(
            update={"raw_ocr_text": raw_text},
        )

        logger.info("Receipt result saving started")

        outcome = service.save_result(
            receipt_id=parsed_receipt_id,
            result=result,
            processing_version=processing_version,
        )

        logger.info(
            "Receipt job finished outcome=%s",
            outcome.value,
        )

    except Exception as error:
        logger.exception("Receipt processing failed")

        try:
            service.mark_failed(
                parsed_receipt_id,
                error=error,
                processing_version=processing_version,
            )
        except Exception:
            logger.exception(
                "Could not persist receipt processing error"
            )

        raise
