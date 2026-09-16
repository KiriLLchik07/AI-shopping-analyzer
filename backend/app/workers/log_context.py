from uuid import NAMESPACE_URL, uuid5

from rq.job import Job

from backend.app.core.logging import (
    LogValue,
    normalize_correlation_id,
)


def get_job_log_context(job: Job) -> dict[str, LogValue]:
    fallback = str(uuid5(NAMESPACE_URL, f"rq-job:{job.id}"))

    correlation_id = normalize_correlation_id(
        job.meta.get("correlation_id"),
        fallback=fallback,
    )

    receipt_id = str(job.args[0]) if job.args else "-"
    processing_version = job.args[1] if len(job.args) > 1 else 1

    return {
        "correlation_id": correlation_id,
        "job_id": job.id,
        "receipt_id": receipt_id,
        "processing_version": processing_version,
    }
