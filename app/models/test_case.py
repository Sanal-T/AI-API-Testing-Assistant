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

    body: dict[str, Any] | None = None

    expected_status: list[int] = Field(default_factory=list)