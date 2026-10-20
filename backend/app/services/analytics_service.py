from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.repositories.analytics_repository import AnalyticsRepository
from backend.app.schemas.analytics import (
    AnalyticsCategoriesResponse,
    AnalyticsProductsResponse,
    AnalyticsStoresResponse,
    AnalyticsSummaryResponse,
    AnalyticsTrendsResponse,
    ProductSort,
    ResolvedAnalyticsPeriod,
    TrendGroup,
)


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self.repository = AnalyticsRepository(session)

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
