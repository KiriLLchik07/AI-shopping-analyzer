from calendar import monthrange
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AnalyticsSettings
from backend.app.repositories.llm_report_data_repository import LlmReportDataRepository
from backend.app.schemas.analytics import AnalyticsPeriodParams
from backend.app.schemas.llm_report import MonthlyReportData, MonthlyReportParams
from backend.app.services.analytics_period_service import resolve_analytics_period


class LlmReportDataService:
    def __init__(
        self, session_factory: sessionmaker[Session], settings: AnalyticsSettings
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def build_monthly(
        self, user_id: UUID, params: MonthlyReportParams
    ) -> MonthlyReportData:
        params = MonthlyReportParams.model_validate(params)
        month = params.month
        previous_end = month - timedelta(days=1)
        current = resolve_analytics_period(
            AnalyticsPeriodParams(
                date_from=month,
                date_to=month.replace(day=monthrange(month.year, month.month)[1]),
                timezone=params.timezone,
            ),
            self.settings,
        )
        previous = resolve_analytics_period(
            AnalyticsPeriodParams(
                date_from=previous_end.replace(day=1),
                date_to=previous_end,
                timezone=params.timezone,
            ),
            self.settings,
        )
        with self.session_factory.begin() as session:
            session.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
            return LlmReportDataRepository(session).monthly_aggregates(
                user_id, current, previous
            )
