import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.llm.exceptions import (
    LlmResponseValidationError,
    NoConfirmedPurchasesError,
)
from backend.app.llm.interface import LlmProvider
from backend.app.llm.prompts.monthly_v1 import (
    PROMPT_VERSION,
    REPORT_SCHEMA_VERSION,
    SYSTEM_PROMPT,
    build_monthly_request,
)
from backend.app.llm.report_generator import MonthlyReportGenerator
from backend.app.schemas.llm_report import (
    MonthlyReportData,
    MonthlyReportParams,
    MonthlyReportResult,
    ReportRecommendation,
)


def input_data(**updates):
    values = {
        "timezone": "Asia/Omsk",
        "current": {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "total_amount": "5000.00",
            "purchase_count": 10,
        },
        "previous": {
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "total_amount": "4000.00",
            "purchase_count": 8,
        },
        "categories": [
            {
                "category_name": "Продукты",
                "total_amount": "5000.00",
                "purchase_count": 10,
            }
        ],
        "weekly_trends": [
            {
                "bucket_start": "2026-08-31",
                "total_amount": "5000.00",
                "purchase_count": 10,
            }
        ],
        "rules": ["Меньше тратить на кафе"],
        **updates,
    }
    return MonthlyReportData.model_validate(values)


def output_data(count=3):
    return {
        "schema_version": "monthly-report-v1",
        "summary": "На продукты потрачено 5 000 ₽.",
        "recommendations": [
            {
                "title": f"План покупок {i}",
                "reason": "На продукты потрачено 5 000 ₽.",
                "action": f"Составьте список покупок на неделю {i}.",
            }
            for i in range(count)
        ],
    }


class TestProvider(LlmProvider):
    __test__ = False

    def __init__(self, output):
        self.output = output
        self.calls = []

    @property
    def provider_name(self):
        return "test-local"

    @property
    def model_name(self):
        return "test-model"

    def generate(self, request, *, response_model):
        self.calls.append((request, response_model))
        return self.output


def test_prompt_is_versioned_and_request_contains_only_aggregate_contract():
    data = input_data()
    request = build_monthly_request(data)
    assert PROMPT_VERSION == "monthly-v1"
    assert REPORT_SCHEMA_VERSION == "monthly-report-v1"
    assert request.prompt_version == PROMPT_VERSION
    assert request.system_prompt == SYSTEM_PROMPT
    assert set(request.payload) == {
        "schema_version",
        "currency",
        "timezone",
        "current",
        "previous",
        "categories",
        "weekly_trends",
        "rules",
    }
    assert set(request.payload["current"]) == {
        "date_from",
        "date_to",
        "total_amount",
        "purchase_count",
    }
    assert request.payload["current"]["total_amount"] == "5000.00"
    assert data.current.total_amount == Decimal("5000.00")
    assert request == build_monthly_request(data)
    request.payload["current"]["total_amount"] = "0.00"
    assert data.current.total_amount == Decimal("5000.00")
    assert build_monthly_request(data).payload["current"]["total_amount"] == "5000.00"


def test_monthly_v1_template_is_frozen():
    assert hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest() == (
        "816f8fc641bf393bb8499fd84b49b1ef7fb5db357ad119f2fae551bbdd62c268"
    )


def test_input_construct_does_not_bypass_validation_before_provider_call():
    data = input_data()
    object.__setattr__(data.current, "purchase_count", -1)
    provider = TestProvider(output_data())
    with pytest.raises(ValidationError):
        MonthlyReportGenerator(provider).generate(data)
    assert provider.calls == []


def test_provider_validation_error_is_converted_to_safe_error():
    class ValidatingProvider(TestProvider):
        def generate(self, request, *, response_model):
            return response_model.model_validate({"summary": "PRIVATE RESPONSE"})

    with pytest.raises(LlmResponseValidationError) as caught:
        MonthlyReportGenerator(ValidatingProvider(None)).generate(input_data())
    assert "PRIVATE RESPONSE" not in str(caught.value)


@pytest.mark.parametrize(
    "field", ["raw_ocr_text", "image", "image_object_key", "user_id", "receipt_id"]
)
def test_aggregate_dto_rejects_receipt_and_identity_fields(field):
    values = input_data().model_dump(mode="json")
    values[field] = "PRIVATE"
    with pytest.raises(ValidationError):
        build_monthly_request(values)


@pytest.mark.parametrize(
    "section", ["current", "previous", "categories", "weekly_trends"]
)
def test_nested_payload_cannot_include_raw_fields(section):
    values = input_data().model_dump(mode="json")
    target = (
        values[section][0] if isinstance(values[section], list) else values[section]
    )
    target["raw_ocr_text"] = "PRIVATE"
    with pytest.raises(ValidationError):
        build_monthly_request(values)


@pytest.mark.parametrize(
    "month",
    [
        "2026-09-02",
        "2026-09",
        "2026/09/01",
        "0001-01-01",
        "9999-12-01",
        datetime(2026, 9, 1, tzinfo=UTC),
        True,
    ],
)
def test_month_params_reject_unsupported_dates(month):
    with pytest.raises(ValidationError):
        MonthlyReportParams(month=month)


def test_month_params_accept_iso_date_and_iana_timezone():
    value = MonthlyReportParams(month="2026-09-01", timezone="Asia/Omsk")
    assert value.month == date(2026, 9, 1)


@pytest.mark.parametrize("zone", ["", "Omsk", "Mars/Test"])
def test_month_params_reject_invalid_timezone(zone):
    with pytest.raises(ValidationError):
        MonthlyReportParams(month="2026-09-01", timezone=zone)


def test_totals_reject_partial_month_and_unrelated_comparison():
    values = input_data().model_dump(mode="json")
    values["current"]["date_to"] = "2026-09-20"
    with pytest.raises(ValidationError):
        MonthlyReportData.model_validate(values)
    values = input_data().model_dump(mode="json")
    values["previous"]["date_from"] = "2026-07-01"
    values["previous"]["date_to"] = "2026-07-31"
    with pytest.raises(ValidationError):
        MonthlyReportData.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_amount", "-0.01"),
        ("total_amount", "NaN"),
        ("purchase_count", True),
        ("purchase_count", -1),
    ],
)
def test_aggregate_values_are_validated(field, value):
    values = input_data().model_dump(mode="json")
    values["current"][field] = value
    with pytest.raises(ValidationError):
        MonthlyReportData.model_validate(values)


@pytest.mark.parametrize(
    "rules", [[" "], ["a" * 2001], ["valid"] * 21, [{"raw_ocr_text": "PRIVATE"}]]
)
def test_rules_are_bounded_text(rules):
    with pytest.raises(ValidationError):
        input_data(rules=rules)


@pytest.mark.parametrize("count", [3, 4, 5])
@pytest.mark.parametrize("kind", ["dict", "json", "model"])
def test_generator_validates_structured_response(count, kind):
    output = output_data(count)
    if kind == "json":
        output = json.dumps(output)
    elif kind == "model":
        output = MonthlyReportResult.model_validate(output)
    provider = TestProvider(output)
    result = MonthlyReportGenerator(provider).generate(input_data())
    assert isinstance(result, MonthlyReportResult)
    assert len(result.recommendations) == count
    assert provider.calls[0][1] is MonthlyReportResult
    assert provider.calls[0][0].prompt_version == "monthly-v1"


@pytest.mark.parametrize(
    "output",
    ["PRIVATE not json", {}, None, [], output_data(0), output_data(2), output_data(6)],
)
def test_generator_rejects_invalid_provider_output_without_echoing_it(output):
    with pytest.raises(LlmResponseValidationError) as caught:
        MonthlyReportGenerator(TestProvider(output)).generate(input_data())
    assert "PRIVATE" not in str(caught.value)
    assert "неверного формата" in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", "   "),
        ("summary", 42),
        ("schema_version", "unknown"),
        ("execute_sql", "DELETE FROM receipts"),
    ],
)
def test_output_fields_are_strict_and_no_actions_are_accepted(field, value):
    output = output_data()
    output[field] = value
    with pytest.raises(LlmResponseValidationError):
        MonthlyReportGenerator(TestProvider(output)).generate(input_data())


def test_nested_output_rejects_extra_fields_and_blank_actions():
    output = output_data()
    output["recommendations"][0]["tool_call"] = "update_receipt"
    with pytest.raises(ValidationError):
        MonthlyReportResult.model_validate(output)
    output = output_data()
    output["recommendations"][0]["action"] = " "
    with pytest.raises(ValidationError):
        MonthlyReportResult.model_validate(output)


def test_unvalidated_model_construct_does_not_bypass_response_validation():
    output = MonthlyReportResult.model_construct(**output_data())
    object.__setattr__(output, "summary", " ")
    with pytest.raises(LlmResponseValidationError):
        MonthlyReportGenerator(TestProvider(output)).generate(input_data())
    output = MonthlyReportResult.model_validate(output_data())
    invalid = ReportRecommendation.model_construct(title="", reason=" ", action=" ")
    object.__setattr__(output, "recommendations", (invalid,) * 3)
    with pytest.raises(LlmResponseValidationError):
        MonthlyReportGenerator(TestProvider(output)).generate(input_data())


def test_empty_month_does_not_call_provider():
    values = input_data().model_dump(mode="json")
    values["current"].update(total_amount="0.00", purchase_count=0)
    values["categories"] = []
    values["weekly_trends"] = []
    provider = TestProvider(output_data())
    with pytest.raises(NoConfirmedPurchasesError):
        MonthlyReportGenerator(provider).generate(
            MonthlyReportData.model_validate(values)
        )
    assert provider.calls == []


def test_response_json_schema_forbids_extra_fields_and_limits_recommendations():
    schema = MonthlyReportResult.model_json_schema()
    assert schema["additionalProperties"] is False
    recommendations = schema["properties"]["recommendations"]
    assert recommendations["minItems"] == 3
    assert recommendations["maxItems"] == 5
    assert schema["$defs"]["ReportRecommendation"]["additionalProperties"] is False


def test_generator_rejects_repeated_actions_with_different_titles():
    output = output_data()
    output["recommendations"][0]["action"] = "Составьте список покупок."
    output["recommendations"][1]["action"] = "  СОСТАВЬТЕ   СПИСОК ПОКУПОК. "
    with pytest.raises(LlmResponseValidationError):
        MonthlyReportGenerator(TestProvider(output)).generate(input_data())
