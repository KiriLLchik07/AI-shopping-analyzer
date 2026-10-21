from typing import Annotated

from fastapi import Depends

from backend.app.core.config import analytics_settings
from backend.app.db.session import SessionLocal
from backend.app.llm.factory import get_llm_provider
from backend.app.llm.interface import LlmProvider
from backend.app.services.llm_report_read_service import LlmReportReadService
from backend.app.services.llm_report_service import LlmReportService


def get_llm_report_service(
    provider: Annotated[LlmProvider, Depends(get_llm_provider)],
) -> LlmReportService:
    return LlmReportService(SessionLocal, provider, analytics_settings)


def get_llm_report_read_service() -> LlmReportReadService:
    return LlmReportReadService(SessionLocal)
