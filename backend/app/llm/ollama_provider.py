import json
import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.core.config import LlmSettings
from backend.app.llm.exceptions import (
    LlmConfigurationError,
    LlmResponseValidationError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from backend.app.llm.interface import LlmProvider, ResponseT
from backend.app.schemas.llm import LlmRequest

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _ModelInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    capabilities: tuple[str, ...]
    remote_host: str | None = None
    remote_model: str | None = None


class _ChatMessage(BaseModel):
    model_config = ConfigDict(strict=True)

    role: Literal["assistant"]
    content: str = Field(min_length=1, pattern=r"\S")
    tool_calls: tuple[dict, ...] = ()


class _ChatResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    message: _ChatMessage
    done: Literal[True]
    done_reason: Literal["stop"]


class OllamaLlmProvider(LlmProvider):
    def __init__(
        self, config: LlmSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.config = config
        self.transport = transport

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.config.model_name

    def generate(
        self, request: LlmRequest, *, response_model: type[ResponseT]
    ) -> ResponseT:
        request = LlmRequest.model_validate(request)
        schema = response_model.model_json_schema()
        body = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": request.system_prompt
                    + "\nJSON Schema:\n"
                    + json.dumps(schema, ensure_ascii=False, allow_nan=False),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        request.payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        allow_nan=False,
                    ),
                },
            ],
            "format": schema,
            "stream": False,
            "keep_alive": self.config.keep_alive_seconds,
            "options": {
                "temperature": self.config.temperature,
                "seed": self.config.seed,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
        }
        if self.config.think is not None:
            body["think"] = self.config.think
        timeout = httpx.Timeout(
            self.config.timeout_seconds, connect=self.config.connect_timeout_seconds
        )
        with httpx.Client(
            base_url=self.config.base_url,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempt in range(len(self.config.retry_intervals_seconds) + 1):
                try:
                    self._ensure_local_model(client)
                    content = self._post(client, "/api/chat", body)
                    response = _ChatResponse.model_validate_json(content)
                    if response.message.tool_calls:
                        raise LlmResponseValidationError()
                    return response_model.model_validate_json(response.message.content)
                except httpx.TimeoutException:
                    error = LlmTimeoutError()
                except httpx.TransportError:
                    error = LlmUnavailableError()
                except LlmUnavailableError as unavailable:
                    error = unavailable
                except ValidationError:
                    raise LlmResponseValidationError() from None
                if attempt == len(self.config.retry_intervals_seconds):
                    logger.warning(
                        "LLM generation failed code=%s attempts=%s",
                        error.code,
                        attempt + 1,
                    )
                    raise error from None
                delay = self.config.retry_intervals_seconds[attempt]
                logger.warning(
                    "Retrying LLM generation code=%s attempt=%s backoff_seconds=%s",
                    error.code,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("Unreachable retry state")

    def _ensure_local_model(self, client: httpx.Client) -> None:
        info = _ModelInfo.model_validate_json(
            self._post(client, "/api/show", {"model": self.model_name})
        )
        if info.remote_host or info.remote_model:
            raise LlmConfigurationError(
                "Облачная модель отключена. Выберите локальную модель Ollama."
            )
        if "completion" not in info.capabilities:
            raise LlmConfigurationError(
                "Настроенная модель не поддерживает генерацию текста."
            )

    def _post(self, client: httpx.Client, path: str, body: dict) -> bytes:
        with client.stream("POST", path, json=body) as response:
            if response.status_code in RETRYABLE_STATUSES:
                raise LlmUnavailableError()
            if response.status_code == 404:
                raise LlmConfigurationError(
                    "Модель Ollama не найдена. Загрузите настроенную модель."
                )
            if not response.is_success:
                raise LlmConfigurationError()
            content = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                if len(content) + len(chunk) > self.config.max_response_bytes:
                    raise LlmResponseValidationError()
                content.extend(chunk)
            return bytes(content)
