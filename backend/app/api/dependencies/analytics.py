from typing import Annotated

from fastapi import HTTPException, Query

from backend.app.core.config import analytics_settings
from backend.app.schemas.analytics import AnalyticsPeriodParams, ResolvedAnalyticsPeriod
from backend.app.services.analytics_period_service import resolve_analytics_period


def get_analytics_period(
    params: Annotated[AnalyticsPeriodParams, Query()],
) -> ResolvedAnalyticsPeriod:
    try:
        return resolve_analytics_period(params, analytics_settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
