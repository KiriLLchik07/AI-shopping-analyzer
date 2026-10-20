from pydantic import BaseModel, ConfigDict, Field, JsonValue


class LlmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    prompt_version: str = Field(min_length=1, max_length=64, pattern=r"\S")
    system_prompt: str = Field(min_length=1, pattern=r"\S")
    payload: dict[str, JsonValue]
