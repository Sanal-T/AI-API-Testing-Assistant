from enum import Enum

from pydantic import BaseModel, Field

from app.models.test_case import TestCase


class ExecutionOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    UNVERIFIED = "unverified"
    SKIPPED = "skipped"


class ExecutionErrorKind(str, Enum):
    NETWORK = "network"
    TIMEOUT = "timeout"


class TestExecutionResult(BaseModel):
    """Execution observations kept separate from the test definition."""

    test_case: TestCase
    outcome: ExecutionOutcome
    actual_status: int | None = Field(default=None, ge=100, le=599)
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: str | None = None
    duration_ms: float = Field(ge=0)
    error_kind: ExecutionErrorKind | None = None
    error: str | None = None
    response_truncated: bool = False
