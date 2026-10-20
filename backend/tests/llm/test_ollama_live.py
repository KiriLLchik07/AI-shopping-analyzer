import time
from pathlib import Path

import pytest

from backend.app.core.config import LlmSettings
from backend.app.llm.ollama_provider import OllamaLlmProvider
from backend.app.llm.report_generator import MonthlyReportGenerator
from backend.app.schemas.llm_report import MonthlyReportData, MonthlyReportResult

pytestmark = pytest.mark.llm


def test_real_local_model_returns_valid_monthly_report():
    data = MonthlyReportData.model_validate_json(
        (Path(__file__).parent / "fixtures" / "monthly.json").read_text(
            encoding="utf-8"
        )
    )
    provider = OllamaLlmProvider(LlmSettings(retry_intervals_seconds=()))
    started = time.perf_counter()
    result = MonthlyReportGenerator(provider).generate(data)
    assert isinstance(result, MonthlyReportResult)
    assert result.schema_version == "monthly-report-v1"
    assert 3 <= len(result.recommendations) <= 5
    print(
        f"model={provider.model_name} elapsed_seconds={time.perf_counter() - started:.2f}"
    )
    print(result.model_dump_json())
