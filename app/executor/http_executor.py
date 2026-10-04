from dataclasses import dataclass
from typing import Any

from app.models.test_case import TestCase


DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_000_000
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_BLOCKED_REQUEST_HEADERS = {"host", "content-length", "transfer-encoding"}
_SENSITIVE_RESPONSE_HEADERS = {"authorization", "proxy-authenticate", "set-cookie"}


@dataclass(frozen=True)
class ExecutionResult:
    """Observed result from one HTTP request and its status assertion."""

    test_name: str
    expected_status: list[int] | None
    actual_status: int | None
    passed: bool | None
    response_headers: dict[str, str]
    response_body: str | None
    duration_ms: float
    error: str | None = None
    response_truncated: bool = False
