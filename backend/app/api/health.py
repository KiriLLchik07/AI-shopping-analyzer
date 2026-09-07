from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from backend.app.api.dependencies.storage import get_object_storage
from backend.app.schemas.response import (
    HealthLiveResponse,
    HealthReadyResponse,
    HealthServicesResponse,
)
from backend.app.services.health_service import HealthService
from backend.app.storage.interface import ObjectStorage

router = APIRouter()


@router.get("/health/live", response_model=HealthLiveResponse)
def check_live_backend() -> HealthLiveResponse:
    return HealthLiveResponse(status="ok")


@router.get("/health/ready", response_model=HealthReadyResponse)
def check_infra_ready(
    response: Response,
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> HealthReadyResponse:
    checks = HealthService(object_storage).check_ready()
    is_ready = all(checks.values())

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthReadyResponse(
        status="ok" if is_ready else "unavailable",
        services=HealthServicesResponse(**checks),
    )
