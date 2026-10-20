from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.repositories.analytics_repository import AnalyticsRepository
from backend.app.schemas.analytics import (
    AnalyticsCategoriesResponse,
    AnalyticsMonthComparisonResponse,
    AnalyticsProductsResponse,
    AnalyticsStoresResponse,
    AnalyticsSummaryResponse,
    AnalyticsTrendsResponse,
    MonthComparisonPeriods,
    MonthComparisonTotal,
    ProductSort,
    ResolvedAnalyticsPeriod,
    TrendGroup,
)


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self.repository = AnalyticsRepository(session)

    def month_comparison(
        self, user_id: UUID, periods: MonthComparisonPeriods
    ) -> AnalyticsMonthComparisonResponse:
        totals = self.repository.month_comparison(user_id, periods)
        current_amount, previous_amount = (
            totals["current_total_amount"],
            totals["previous_total_amount"],
        )
        current_count, previous_count = (
            totals["current_purchase_count"],
            totals["previous_purchase_count"],
        )
        return AnalyticsMonthComparisonResponse(
            timezone=periods.timezone,
            as_of=periods.as_of,
            current=MonthComparisonTotal(
                start_at=periods.current_start,
                end_at=periods.current_end,
                total_amount=current_amount,
                purchase_count=current_count,
            ),
            previous=MonthComparisonTotal(
                start_at=periods.previous_start,
                end_at=periods.previous_end,
                total_amount=previous_amount,
                purchase_count=previous_count,
            ),
            amount_change=current_amount - previous_amount,
            amount_change_percent=_percentage_change(current_amount, previous_amount),
            purchase_count_change=current_count - previous_count,
            purchase_count_change_percent=_percentage_change(
                Decimal(current_count), Decimal(previous_count)
            ),
        )

    def summary(
        self, user_id: UUID, period: ResolvedAnalyticsPeriod
    ) -> AnalyticsSummaryResponse:
        return AnalyticsSummaryResponse(
            period=period, **self.repository.summary(user_id, period)
        )

    def categories(
        self, user_id: UUID, period: ResolvedAnalyticsPeriod
    ) -> AnalyticsCategoriesResponse:
        return AnalyticsCategoriesResponse(
            period=period, items=self.repository.categories(user_id, period)
        )

    def products(
        self,
        user_id: UUID,
        period: ResolvedAnalyticsPeriod,
        limit: int,
        sort_by: ProductSort,
    ) -> AnalyticsProductsResponse:
        return AnalyticsProductsResponse(
            period=period,
            limit=limit,
            sort_by=sort_by,
            items=self.repository.products(user_id, period, limit, sort_by),
        )

    def stores(
        self, user_id: UUID, period: ResolvedAnalyticsPeriod, limit: int
    ) -> AnalyticsStoresResponse:
        return AnalyticsStoresResponse(
            period=period,
            limit=limit,
            items=self.repository.stores(user_id, period, limit),
        )

    def trends(
        self, user_id: UUID, period: ResolvedAnalyticsPeriod, group_by: TrendGroup
    ) -> AnalyticsTrendsResponse:
        return AnalyticsTrendsResponse(
            period=period,
            group_by=group_by,
            points=self.repository.trends(user_id, period, group_by),
        )


def _percentage_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return Decimal("0.00") if current == 0 else None
    return ((current - previous) * 100 / previous).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
