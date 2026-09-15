import logging
from uuid import UUID

from rq import get_current_job

from backend.app.db.session import SessionLocal
from backend.app.models import Receipt

logger = logging.getLogger(__name__)

def process_receipt(receipt_id: str) -> str:
    parsed_receipt_id = UUID(receipt_id)

    job = get_current_job()
    job_id = job.id if job else "manual"

    logger.info(
        "Receipt job started receipt_id=%s job_id=%s",
        receipt_id,
        job_id,
    )

    with SessionLocal() as session:
        receipt = session.get(Receipt, parsed_receipt_id)

        if receipt is None:
            logger.info(
                "Receipt job skipped: receipt no longer exists "
                "receipt_id=%s job_id=%s",
                receipt_id,
                job_id,
            )
            return

        image_object_key = receipt.image_object_key

        logger.info(
            "Receipt loaded for processing receipt_id=%s job_id=%s "
            "image_reference_available=%s",
            receipt_id,
            job_id,
            bool(image_object_key),
        )

