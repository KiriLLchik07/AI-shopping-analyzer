import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AnalyticsSettings
from backend.app.core.exceptions import (
    InvalidSessionError,
    LlmReportInputError,
    LlmReportStorageUnavailableError,
)
from backend.app.llm.exceptions import LlmConfigurationError
from backend.app.llm.interface import LlmProvider
from backend.app.llm.prompts.monthly_v1 import PROMPT_VERSION
from backend.app.llm.report_generator import MonthlyReportGenerator
from backend.app.repositories.llm_report_repository import LlmReportRepository
from backend.app.schemas.llm_report import (
    LlmProviderInfo,
    LlmReportResponse,
    MonthlyReportParams,
)
from backend.app.services.llm_report_data_service import LlmReportDataService

logger = logging.getLogger(__name__)


class LlmReportService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: LlmProvider,
        settings: AnalyticsSettings,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.data_service = LlmReportDataService(session_factory, settings)

    def create_monthly(
        self, user_id: UUID, params: MonthlyReportParams
    ) -> LlmReportResponse:
        try:
            provider_info = LlmProviderInfo(
                provider_name=self.provider.provider_name,
                model_name=self.provider.model_name,
            )
        except ValidationError:
            raise LlmConfigurationError() from None
        try:
            try:
                data = self.data_service.build_monthly(user_id, params)
            except ValueError:
                raise LlmReportInputError() from None
            result = MonthlyReportGenerator(self.provider).generate(data)
            with self.session_factory.begin() as session:
                repository = LlmReportRepository(session)
                if not repository.lock_owner(user_id):
                    raise InvalidSessionError()
                report = repository.create(
                    user_id, data, result, provider_info, PROMPT_VERSION
                )
                response = LlmReportResponse.model_validate(report)
        except SQLAlchemyError:
            logger.warning("Monthly LLM report database operation failed")
            raise LlmReportStorageUnavailableError() from None
        logger.info("Monthly LLM report saved report_id=%s", response.report_id)
        return response
