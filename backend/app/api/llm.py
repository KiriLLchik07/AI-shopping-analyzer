from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from backend.app.api.dependencies.auth import get_current_user_id
from backend.app.api.dependencies.llm import get_llm_report_service
from backend.app.schemas.llm_report import LlmReportResponse, MonthlyReportParams
from backend.app.services.llm_report_service import LlmReportService

router = APIRouter(prefix="/api/llm/reports", tags=["llm"])


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
