from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import LlmReport, User
from backend.app.schemas.llm_report import (
    LlmProviderInfo,
    MonthlyReportData,
    MonthlyReportResult,
)


class LlmReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_owner(self, user_id: UUID) -> bool:
        owner = self.session.scalar(
            select(User.user_id)
            .where(User.user_id == user_id)
            .with_for_update(read=True, key_share=True)
        )
        return owner is not None

    def create(
        self,
        user_id: UUID,
        data: MonthlyReportData,
        result: MonthlyReportResult,
        provider: LlmProviderInfo,
        prompt_version: str,
    ) -> LlmReport:
        report = LlmReport(
            user_id=user_id,
            period_start=data.current.date_from,
            period_end=data.current.date_to,
            timezone=data.timezone,
            input_data=data.model_dump(mode="json"),
            report_data=result.model_dump(mode="json"),
            prompt_version=prompt_version,
            schema_version=result.schema_version,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
        )
        self.session.add(report)
        self.session.flush()
        return report
