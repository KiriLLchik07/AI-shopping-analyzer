class LlmResponseValidationError(Exception):
    """Ответ провайдера не соответствует схеме отчёта."""


class NoConfirmedPurchasesError(Exception):
    """Нет подтверждённых покупок для отчёта."""
