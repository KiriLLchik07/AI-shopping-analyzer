from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies.analytics import (
    get_analytics_period,
    get_month_comparison_periods,
)
from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import get_db
from backend.app.models import User
from backend.app.schemas.analytics import (
    AnalyticsCategoriesResponse,
    AnalyticsLimitParams,
    AnalyticsMonthComparisonParams,
    AnalyticsMonthComparisonResponse,
    AnalyticsPeriodParams,
    AnalyticsProductsParams,
    AnalyticsProductsResponse,
    AnalyticsStoresResponse,
    AnalyticsSummaryResponse,
    AnalyticsTrendsParams,
    AnalyticsTrendsResponse,
)
from backend.app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/month-comparison", response_model=AnalyticsMonthComparisonResponse)
def month_comparison(
    params: Annotated[AnalyticsMonthComparisonParams, Query()],
    db: Database,
    user: CurrentUser,
) -> AnalyticsMonthComparisonResponse:
    return AnalyticsService(db).month_comparison(
        user.user_id, get_month_comparison_periods(params)
    )


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def summary(
    params: Annotated[AnalyticsPeriodParams, Query()], db: Database, user: CurrentUser
) -> AnalyticsSummaryResponse:
    return AnalyticsService(db).summary(user.user_id, get_analytics_period(params))


@router.get("/categories", response_model=AnalyticsCategoriesResponse)
def categories(
    params: Annotated[AnalyticsPeriodParams, Query()], db: Database, user: CurrentUser
) -> AnalyticsCategoriesResponse:
    return AnalyticsService(db).categories(user.user_id, get_analytics_period(params))


@router.get("/products/top", response_model=AnalyticsProductsResponse)
def products(
    params: Annotated[AnalyticsProductsParams, Query()], db: Database, user: CurrentUser
) -> AnalyticsProductsResponse:
    return AnalyticsService(db).products(
        user.user_id, get_analytics_period(params), params.limit, params.sort_by
    )


@router.get("/stores", response_model=AnalyticsStoresResponse)
def stores(
    params: Annotated[AnalyticsLimitParams, Query()], db: Database, user: CurrentUser
) -> AnalyticsStoresResponse:
    return AnalyticsService(db).stores(
        user.user_id, get_analytics_period(params), params.limit
    )


@router.get("/trends", response_model=AnalyticsTrendsResponse)
def trends(
    params: Annotated[AnalyticsTrendsParams, Query()], db: Database, user: CurrentUser
) -> AnalyticsTrendsResponse:
    return AnalyticsService(db).trends(
        user.user_id, get_analytics_period(params), params.group_by
    )
