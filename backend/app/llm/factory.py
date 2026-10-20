from functools import lru_cache

from backend.app.core.config import llm_settings
from backend.app.llm.interface import LlmProvider
from backend.app.llm.ollama_provider import OllamaLlmProvider


@lru_cache
def get_llm_provider() -> LlmProvider:
    return OllamaLlmProvider(llm_settings)
