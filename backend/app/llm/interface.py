from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from backend.app.schemas.llm import LlmRequest

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class LlmProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self, request: LlmRequest, *, response_model: type[ResponseT]
    ) -> ResponseT:
        """Возвращает ответ, проверенный по переданной Pydantic-схеме."""
        raise NotImplementedError
