from abc import ABC, abstractmethod

from backend.app.schemas.ocr import OcrResult

class OcrProvider(ABC):
    @abstractmethod
    def recognize(self, image: bytes) -> OcrResult:
        """
        Распознает текст на одном изображении.

        Args:
            image:
                Содержимое закодированного файла изображения,
                например JPEG или PNG.

        Returns:
            Результат распознавания с текстом и confidence.
            raw_text может быть пустым, если текст не обнаружен.
            confidence=None означает отсутствие оценки.

        Raises:
            OcrConfigurationError:
                Провайдер не настроен или имеет неверную конфигурацию.

            OcrRecognitionError:
                Провайдер не смог выполнить распознавание.
        """
        raise NotImplementedError
