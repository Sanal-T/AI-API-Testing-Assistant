from pydantic import BaseModel, Field

from app.models.test_case import TestCase


class TestRunRequest(BaseModel):
    """Explicit target and safety settings for one bounded execution batch."""

    test_cases: list[TestCase] = Field(min_length=1, max_length=100)
    base_url: str
    allowed_hosts: set[str] = Field(min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_query_params: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=10.0, gt=0, le=60)
    allow_private_network: bool = False
    allow_mutating_methods: bool = False
    analyze_failures: bool = False
