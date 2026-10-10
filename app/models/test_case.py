from typing import Any

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    name: str
    method: str
    path: str
    type: str

    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, Any] = Field(default_factory=dict)
    request_header_exclusions: set[str] = Field(default_factory=set)
    request_query_exclusions: set[str] = Field(default_factory=set)

    body: dict[str, Any] | None = None

    expected_status: list[int] | None = None
    rationale: str | None = None

    # Contract Validation & Advanced Assertions
    expected_response_schema: dict[str, Any] | None = None
    expected_headers: dict[str, str] = Field(default_factory=dict)
    json_path_assertions: list[dict[str, Any]] = Field(default_factory=list)
    max_duration_ms: float | None = None
