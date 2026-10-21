from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from backend.app.api.dependencies.auth import get_current_user_id
from backend.app.api.dependencies.llm import (
    get_llm_report_read_service,
    get_llm_report_service,
)
from backend.app.schemas.llm_report import (
    LlmReportListParams,
    LlmReportListResponse,
    LlmReportResponse,
    MonthlyReportParams,
)
from backend.app.services.llm_report_read_service import LlmReportReadService
from backend.app.services.llm_report_service import LlmReportService

router = APIRouter(prefix="/api/llm/reports", tags=["llm"])


@router.get("", response_model=LlmReportListResponse)
def list_reports(
    params: Annotated[LlmReportListParams, Query()],
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    service: Annotated[LlmReportReadService, Depends(get_llm_report_read_service)],
    response: Response,
) -> LlmReportListResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.list_reports(user_id, params)


@router.post(
    "/monthly", response_model=LlmReportResponse, status_code=status.HTTP_201_CREATED
)
def create_monthly_report(
    params: MonthlyReportParams,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    service: Annotated[LlmReportService, Depends(get_llm_report_service)],
    response: Response,
) -> LlmReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.create_monthly(user_id, params)


@router.get("/{report_id}", response_model=LlmReportResponse)
def get_report(
    report_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    service: Annotated[LlmReportReadService, Depends(get_llm_report_read_service)],
    response: Response,
) -> LlmReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.get_report(user_id, report_id)
