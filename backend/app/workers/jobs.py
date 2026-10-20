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
from backend.app.schemas.processing_metrics import MetricOutcome, ProcessingStage
from backend.app.services.processing_metrics_service import processing_metrics
from backend.app.services.receipt_pipeline import get_receipt_pipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
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
            "correlation_id": normalize_correlation_id(get_correlation_id()),
            "job_id": "manual",
            "receipt_id": receipt_id,
            "processing_version": processing_version,
        }

    with (
        log_context(**context),
        processing_metrics.measure(ProcessingStage.PIPELINE) as observation,
    ):
        observation.outcome = _process_receipt(
            receipt_id=receipt_id,
            processing_version=processing_version,
        )


def _process_receipt(
    receipt_id: str,
    processing_version: int,
) -> MetricOutcome:
    parsed_receipt_id = UUID(receipt_id)
    service = ReceiptProcessingService(SessionLocal)

    logger.info("Receipt job started")

    with processing_metrics.measure(ProcessingStage.CLAIM) as claim:
        source = service.start_processing(
            parsed_receipt_id,
            processing_version=processing_version,
        )
        if source is None:
            claim.outcome = MetricOutcome.SKIPPED

    if source is None:
        logger.info("Receipt job skipped: receipt missing, active or finished")
        return MetricOutcome.SKIPPED

    try:
        with processing_metrics.measure(ProcessingStage.SETUP):
            pipeline = get_receipt_pipeline()

        logger.info("Receipt preprocessing started")
        with processing_metrics.measure(ProcessingStage.PREPROCESSING):
            preprocessed = pipeline.preprocess_with_metadata(source)

        with processing_metrics.measure(
            ProcessingStage.PERSIST_PREPROCESSING
        ) as orientation:
            advanced = service.advance_status(
                receipt_id=parsed_receipt_id,
                expected_status=ReceiptStatus.PREPROCESSING,
                new_status=ReceiptStatus.OCR_PROCESSING,
                processing_version=processing_version,
                orientation_report=preprocessed.orientation_report,
            )
            if not advanced:
                orientation.outcome = MetricOutcome.STOPPED
        if not advanced:
            logger.info("Receipt job stopped before OCR: state changed")
            return MetricOutcome.STOPPED

        logger.info("Receipt OCR started")
        with processing_metrics.measure(ProcessingStage.OCR):
            ocr_result = pipeline.recognize_with_metadata(preprocessed.image)

        with processing_metrics.measure(ProcessingStage.PERSIST_OCR) as persisted:
            saved = service.save_ocr_result(
                receipt_id=parsed_receipt_id,
                result=ocr_result,
                processing_version=processing_version,
            )
            if not saved:
                persisted.outcome = MetricOutcome.STOPPED
        if not saved:
            logger.info("Receipt job stopped before parsing: state changed")
            return MetricOutcome.STOPPED

        logger.info("Receipt parsing started")
        with processing_metrics.measure(ProcessingStage.PARSING):
            result = pipeline.parse(ocr_result.raw_text)

        logger.info("Receipt result saving started")

        with processing_metrics.measure(ProcessingStage.SAVING) as saving:
            outcome = service.save_result(
                receipt_id=parsed_receipt_id,
                result=result,
                processing_version=processing_version,
            )
            saving.outcome = (
                MetricOutcome.SUCCESS
                if outcome == SaveProcessingOutcome.SAVED
                else MetricOutcome.SKIPPED
                if outcome == SaveProcessingOutcome.ALREADY_SAVED
                else MetricOutcome.STOPPED
            )

        logger.info(
            "Receipt job finished outcome=%s",
            outcome.value,
        )
        return saving.outcome

    except Exception as error:
        logger.exception("Receipt processing failed")

        try:
            service.mark_failed(
                parsed_receipt_id,
                error=error,
                processing_version=processing_version,
            )
        except Exception:
            logger.exception("Could not persist receipt processing error")

        raise
