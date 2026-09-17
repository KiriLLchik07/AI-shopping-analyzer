import logging
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

LogValue = str | int

LOG_FIELDS = (
    "correlation_id",
    "job_id",
    "receipt_id",
    "processing_version",
)

_log_context: ContextVar[dict[str, LogValue] | None] = ContextVar(
    "log_context",
    default=None,
)


def normalize_correlation_id(
    value: object,
    fallback: str | None = None,
) -> str:
    if isinstance(value, str) and len(value) <= 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass

    return fallback if fallback is not None else str(uuid4())


def get_correlation_id() -> str | None:
    context = _log_context.get() or {}
    value = context.get("correlation_id")

    if isinstance(value, str) and value != "-":
        return value

    return None


@contextmanager
def log_context(**values: LogValue) -> Generator[None, None, None]:
    previous = _log_context.get() or {}
    token = _log_context.set({**previous, **values})

    try:
        yield
    finally:
        _log_context.reset(token)


class LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get() or {}

        for field in LOG_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, context.get(field, "-"))

        return True


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def configure_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    handler_name = "application_console"

    if not any(
        handler.get_name() == handler_name
        for handler in root_logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(handler_name)
        handler.setLevel(logging.INFO)
        handler.addFilter(LogContextFilter())
        handler.setFormatter(
            UTCFormatter(
                fmt=(
                    "%(asctime)sZ %(levelname)s %(name)s "
                    "correlation_id=%(correlation_id)s "
                    "job_id=%(job_id)s "
                    "receipt_id=%(receipt_id)s "
                    "processing_version=%(processing_version)s "
                    "%(message)s"
                ),
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

        root_logger.addHandler(handler)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "rq",
        "rq.worker",
        "rq.job",
        "rq.queue",
        "rq.scheduler",
        "rq.cron",
        "rq.worker_pool",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
        logger.disabled = False
        logger.setLevel(logging.INFO)
