class OcrProviderError(Exception):
    """Базовая ошибка OCR-провайдера."""


class OcrConfigurationError(OcrProviderError):
    """Отсутствует необходимая настройка или конфигурация неверна."""


class OcrRecognitionError(OcrProviderError):
    """Движок не смог выполнить распознавание изображения."""
