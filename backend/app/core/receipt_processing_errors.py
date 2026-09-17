from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.storage.exception import ObjectStorageError


class SafeProcessingError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal[
        "processing_conflict", "image_storage_unavailable", "processing_failed"
    ]

    message: str


def get_safe_processing_error(
    error: Exception | None,
) -> SafeProcessingError:
    if isinstance(error, ReceiptProcessingConflictError):
        return SafeProcessingError(
            code="processing_conflict",
            message=(
                "В чеке уже есть товары. "
                "Автоматическая обработка остановлена, "
                "существующие данные сохранены."
            ),
        )

    if isinstance(error, ObjectStorageError):
        return SafeProcessingError(
            code="image_storage_unavailable",
            message=(
                "Не удалось получить изображение чека. "
                "Попробуйте повторить обработку позже."
            ),
        )

    return SafeProcessingError(
        code="processing_failed",
        message=("Не удалось обработать чек. Попробуйте повторить обработку позже."),
    )
