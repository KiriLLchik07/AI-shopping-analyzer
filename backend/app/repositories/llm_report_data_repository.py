from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import UserRule
from backend.app.repositories.analytics_repository import AnalyticsRepository
from backend.app.schemas.analytics import ResolvedAnalyticsPeriod, TrendGroup
from backend.app.schemas.llm_report import (
    MonthlyReportData,
    MonthlyTotals,
    ReportCategory,
)


class LlmReportDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.analytics = AnalyticsRepository(session)

    def monthly_aggregates(
        self,
        user_id: UUID,
        current: ResolvedAnalyticsPeriod,
        previous: ResolvedAnalyticsPeriod,
    ) -> MonthlyReportData:
        categories = self.analytics.categories(user_id, current)
        rules = self.session.scalars(
            select(UserRule.rule_text)
            .where(UserRule.user_id == user_id, UserRule.is_active.is_(True))
            .order_by(UserRule.created_at, UserRule.rule_id)
            .limit(21)
        ).all()
        return MonthlyReportData(
            timezone=current.timezone,
            current=MonthlyTotals(
                date_from=current.date_from,
                date_to=current.date_to,
                **self.analytics.summary(user_id, current),
            ),
            previous=MonthlyTotals(
                date_from=previous.date_from,
                date_to=previous.date_to,
                **self.analytics.summary(user_id, previous),
            ),
            categories=tuple(
                ReportCategory(
                    category_name=row["category_name"],
                    total_amount=row["total_amount"],
                    purchase_count=row["purchase_count"],
                )
                for row in categories
            ),
            weekly_trends=self.analytics.trends(user_id, current, TrendGroup.WEEK),
            rules=rules,
        )
