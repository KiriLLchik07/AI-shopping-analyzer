from pydantic import ValidationError

from backend.app.llm.exceptions import (
    LlmResponseValidationError,
    NoConfirmedPurchasesError,
)
from backend.app.llm.interface import LlmProvider
from backend.app.llm.prompts.monthly_v1 import build_monthly_request
from backend.app.schemas.llm_report import MonthlyReportData, MonthlyReportResult


class MonthlyReportGenerator:
    def __init__(self, provider: LlmProvider) -> None:
        self.provider = provider

    def generate(self, data: MonthlyReportData) -> MonthlyReportResult:
        data = MonthlyReportData.model_validate(data)
        if data.current.purchase_count == 0:
            raise NoConfirmedPurchasesError(
                "За выбранный месяц нет подтверждённых покупок."
            )
        request = build_monthly_request(data)
        try:
            result = self.provider.generate(request, response_model=MonthlyReportResult)
            if isinstance(result, (str, bytes, bytearray)):
                return MonthlyReportResult.model_validate_json(result)
            return MonthlyReportResult.model_validate(result)
        except ValidationError:
            raise LlmResponseValidationError(
                "Модель вернула отчёт неверного формата. Попробуйте ещё раз."
            ) from None
