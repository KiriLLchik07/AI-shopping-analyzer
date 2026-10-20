from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.llm.interface import LlmProvider
from backend.app.schemas.llm import LlmRequest

ResultT = TypeVar("ResultT", bound=BaseModel)


class Summary(BaseModel):
    summary: str


class LocalTestProvider(LlmProvider):
    @property
    def provider_name(self) -> str:
        return "test-local"

    @property
    def model_name(self) -> str:
        return "test-model"

    def generate(
        self, request: LlmRequest, *, response_model: type[ResultT]
    ) -> ResultT:
        return response_model.model_validate({"summary": "Расходы за месяц"})


def request(**values) -> LlmRequest:
    return LlmRequest.model_validate(
        {
            "prompt_version": "monthly-v1",
            "system_prompt": "Составь отчёт по агрегатам.",
            "payload": {"total_amount": "5000.00", "purchase_count": 10},
            **values,
        }
    )


def test_provider_requires_implementation():
    with pytest.raises(TypeError, match="abstract"):
        LlmProvider()


def test_provider_requires_model_and_provider_identity():
    class IncompleteProvider(LlmProvider):
        def generate(self, request, *, response_model):
            return response_model.model_validate({})

    with pytest.raises(TypeError, match="abstract"):
        IncompleteProvider()


def test_provider_returns_requested_pydantic_model():
    provider = LocalTestProvider()
    result = provider.generate(request(), response_model=Summary)
    assert isinstance(result, Summary)
    assert result.summary == "Расходы за месяц"
    assert provider.provider_name == "test-local"
    assert provider.model_name == "test-model"


def test_provider_validates_against_the_requested_schema():
    class DifferentResponse(BaseModel):
        total: int

    with pytest.raises(ValidationError):
        LocalTestProvider().generate(request(), response_model=DifferentResponse)


def test_request_round_trips_json_aggregates():
    value = request(
        payload={"categories": [{"amount": "200.50", "count": 2}], "empty": None}
    )
    assert LlmRequest.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("field", ["image", "raw_ocr_text", "user_id"])
def test_request_rejects_unknown_top_level_fields(field):
    with pytest.raises(ValidationError):
        request(**{field: "unexpected"})


@pytest.mark.parametrize("field", ["system_prompt", "prompt_version"])
@pytest.mark.parametrize("value", ["", " \n\t"])
def test_request_rejects_blank_prompt_metadata(field, value):
    with pytest.raises(ValidationError):
        request(**{field: value})


def test_request_rejects_binary_payload():
    with pytest.raises(ValidationError):
        request(payload={"attachment": b"image"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_request_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        request(payload={"amount": value})
