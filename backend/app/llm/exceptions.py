class LlmProviderError(Exception):
    code = "llm_provider_error"
    message = "Не удалось сформировать отчёт. Попробуйте позже."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class LlmConfigurationError(LlmProviderError):
    code = "llm_configuration_error"
    message = "Не удалось запустить настроенную модель. Проверьте настройки Ollama."


class LlmUnavailableError(LlmProviderError):
    code = "llm_unavailable"
    message = "Сервис формирования отчётов временно недоступен. Попробуйте позже."


class LlmTimeoutError(LlmProviderError):
    code = "llm_timeout"
    message = "Модель не успела сформировать отчёт. Попробуйте позже."


class LlmResponseValidationError(LlmProviderError):
    """Ответ провайдера не соответствует схеме отчёта."""

    code = "llm_invalid_response"
    message = "Модель вернула отчёт неверного формата. Попробуйте ещё раз."


class NoConfirmedPurchasesError(Exception):
    """Нет подтверждённых покупок для отчёта."""
