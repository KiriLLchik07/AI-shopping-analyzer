import secrets
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError

from backend.app.core.config import metrics_settings
from backend.app.schemas.processing_metrics import ProcessingMetricsResponse
from backend.app.services.processing_metrics_service import processing_metrics

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def require_metrics_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = metrics_settings.access_token
    if expected is None or not expected.get_secret_value():
        raise HTTPException(status_code=404, detail="Not found")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(),
        expected.get_secret_value().encode(),
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid metrics credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get(
    "/internal/processing-metrics",
    response_model=ProcessingMetricsResponse,
    dependencies=[Depends(require_metrics_token)],
)
def get_processing_metrics(day: date | None = None) -> ProcessingMetricsResponse:
    try:
        return processing_metrics.snapshot(day or datetime.now(UTC).date())
    except RedisError as error:
        raise HTTPException(
            status_code=503, detail="Metrics temporarily unavailable"
        ) from error
