import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException

from app.analysis.failure_analyzer import (
    OpenAIResponsesProvider,
    analyze_failures,
)
from app.constants import (
    BLOCKED_REQUEST_HEADERS,
    MUTATING_METHODS,
    SUPPORTED_METHODS,
)
from app.executor.http_executor import execute_test_case
from app.models.execution_result import (
    ExecutionOutcome,
    TestExecutionResult,
)
from app.models.test_run import TestRunRequest
from app.report.summary import build_execution_report

logger = logging.getLogger(__name__)

router = APIRouter()
_MUTATING_METHODS = MUTATING_METHODS
_SUPPORTED_METHODS = SUPPORTED_METHODS
_BLOCKED_HEADERS = BLOCKED_REQUEST_HEADERS


@router.post("/run")
def run_tests(request: TestRunRequest) -> dict:
    """Execute a user-selected batch against an explicitly allowlisted target."""
    _validate_run_request(request)
    provider = None
    if request.analyze_failures:
        try:
            provider = OpenAIResponsesProvider.from_environment()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    results = []
    for test_case in request.test_cases:
        headers = {**test_case.headers, **request.request_headers}
        excluded_headers = {name.lower() for name in test_case.request_header_exclusions}
        for name in list(headers):
            if name.lower() in excluded_headers:
                if name in test_case.headers:
                    headers[name] = test_case.headers[name]
                else:
                    headers.pop(name)

        query_params = {**test_case.query_params, **request.request_query_params}
        for name in test_case.request_query_exclusions:
            if name in test_case.query_params:
                query_params[name] = test_case.query_params[name]
            else:
                query_params.pop(name, None)

        test_case = test_case.model_copy(update={
            "headers": headers,
            "query_params": query_params,
        })
        try:
            result = execute_test_case(
                test_case,
                request.base_url,
                allowed_hosts=request.allowed_hosts,
                timeout=request.timeout,
                allow_private_network=request.allow_private_network,
                allow_mutating_methods=request.allow_mutating_methods,
            )
        except ValueError:
            # Keep earlier observations if a later test is rejected before send.
            result = TestExecutionResult(
                test_case=test_case,
                outcome=ExecutionOutcome.ERROR,
                duration_ms=0,
                error="Request was not sent because target validation failed.",
            )
        results.append(result)

    response = {
        "report": build_execution_report(results),
        "analysis": None,
        "analysis_error": None,
    }
    if provider is not None and any(
        result.outcome in {ExecutionOutcome.FAILED, ExecutionOutcome.ERROR}
        for result in results
    ):
        try:
            response["analysis"] = analyze_failures(results, provider=provider).model_dump(mode="json")
        except (RuntimeError, ValueError) as exc:
            logger.warning("AI failure analysis failed: %s", exc, exc_info=True)
            # Preserve the execution report even when the optional provider is unavailable.
            response["analysis_error"] = "Execution completed, but AI analysis was unavailable."
    return response


def _validate_run_request(request: TestRunRequest) -> None:
    if len(request.request_headers) > 50:
        raise HTTPException(status_code=400, detail="No more than 50 request headers may be supplied.")
    for name, value in request.request_headers.items():
        if name.lower() in _BLOCKED_HEADERS:
            raise HTTPException(status_code=400, detail=f"The {name} header is controlled by the executor.")
        if any(character in name or character in value for character in ("\r", "\n")):
            raise HTTPException(status_code=400, detail="Request headers cannot contain line breaks.")
        if len(name) > 256 or len(value) > 8192:
            raise HTTPException(status_code=400, detail="A request header exceeds the allowed size.")
    if len(request.request_query_params) > 50:
        raise HTTPException(status_code=400, detail="No more than 50 request query parameters may be supplied.")
    if any(len(name) > 256 or len(value) > 8192 for name, value in request.request_query_params.items()):
        raise HTTPException(status_code=400, detail="A request query parameter exceeds the allowed size.")

    parsed = urlsplit(request.base_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="base_url must be an absolute HTTP(S) URL without credentials, query, or fragment.")
    normalized_host = parsed.hostname.rstrip(".").lower()
    allowed_hosts = {host.strip("[]").rstrip(".").lower() for host in request.allowed_hosts}
    if normalized_host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="base_url hostname must be included in allowed_hosts.")

    for test_case in request.test_cases:
        method = test_case.method.upper()
        if method not in _SUPPORTED_METHODS:
            raise HTTPException(status_code=400, detail=f"Unsupported HTTP method: {method}")
        if method in _MUTATING_METHODS and not request.allow_mutating_methods:
            raise HTTPException(status_code=400, detail=f"{method} tests require allow_mutating_methods=true.")
        if not test_case.path.startswith("/") or test_case.path.startswith("//"):
            raise HTTPException(status_code=400, detail="Test paths must start with one slash.")
        required_path_params = set(re.findall(r"\{([^{}]+)\}", test_case.path))
        missing_path_params = required_path_params - test_case.path_params.keys()
        if missing_path_params:
            raise HTTPException(status_code=400, detail="A test case is missing a required path parameter.")
