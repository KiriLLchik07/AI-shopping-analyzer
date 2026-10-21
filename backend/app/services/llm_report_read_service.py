import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.exceptions import (
    LlmReportNotFoundError,
    LlmReportStorageUnavailableError,
)
from backend.app.repositories.llm_report_repository import LlmReportRepository
from backend.app.schemas.llm_report import (
    LlmReportListParams,
    LlmReportListResponse,
    LlmReportResponse,
)

logger = logging.getLogger(__name__)


class LlmReportReadService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_reports(
        self, user_id: UUID, params: LlmReportListParams
    ) -> LlmReportListResponse:
        try:
            with self.session_factory.begin() as session:
                session.connection(
                    execution_options={
                        "isolation_level": "REPEATABLE READ",
                        "postgresql_readonly": True,
                    }
                )
                repository = LlmReportRepository(session)
                total = repository.count_for_user(user_id)
                items = repository.list_for_user(
                    user_id, params.page_size, (params.page - 1) * params.page_size
                )
                return LlmReportListResponse(
                    items=items,
                    page=params.page,
                    page_size=params.page_size,
                    total=total,
                    total_pages=(total + params.page_size - 1) // params.page_size,
                )
        except (SQLAlchemyError, ValidationError):
            logger.warning("Could not list saved LLM reports")
            raise LlmReportStorageUnavailableError() from None

    def get_report(self, user_id: UUID, report_id: UUID) -> LlmReportResponse:
        try:
            with self.session_factory.begin() as session:
                repository = LlmReportRepository(session)
                report = repository.get_for_user(user_id, report_id)
                if report is None:
                    raise LlmReportNotFoundError()
                return LlmReportResponse.model_validate(report)
        except (SQLAlchemyError, ValidationError):
            logger.warning("Could not read saved LLM report")
            raise LlmReportStorageUnavailableError() from None
