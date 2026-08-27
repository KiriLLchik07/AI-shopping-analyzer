from fastapi import APIRouter, status, Response
from backend.app.services.health_service import HealthService
from backend.app.schemas.response import (
    HealthLiveResponse,
    HealthReadyResponse,
    HealthServicesResponse,
)

router = APIRouter()


@router.get("/health/live", response_model=HealthLiveResponse)
def check_live_backend() -> HealthLiveResponse:
    return HealthLiveResponse(status="ok")


@router.get("/health/ready", response_model=HealthReadyResponse)
def check_infra_ready(response: Response) -> HealthReadyResponse:
    checks = HealthService().check_ready()
    is_ready = all(checks.values())

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthReadyResponse(
        status="ok" if is_ready else "unavailable",
        services=HealthServicesResponse(**checks),
    )
