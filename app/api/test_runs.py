import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.analysis.failure_analyzer import (
    OpenAIResponsesProvider,
    analyze_failures,
)
from app.constants import (
    BLOCKED_REQUEST_HEADERS,
    MUTATING_METHODS,
    SUPPORTED_METHODS,
)
from app.executor.http_executor import (
    execute_batch,
    execute_batch_stream,
    execute_test_case,
)
from app.models.execution_result import (
    ExecutionOutcome,
    TestExecutionResult,
)
from app.models.test_case import TestCase
from app.models.test_run import TestRunRequest
from app.report.summary import build_execution_report

logger = logging.getLogger(__name__)

router = APIRouter()
_MUTATING_METHODS = MUTATING_METHODS
_SUPPORTED_METHODS = SUPPORTED_METHODS
_BLOCKED_HEADERS = BLOCKED_REQUEST_HEADERS


def _prepare_test_case(test_case: TestCase, request: TestRunRequest) -> TestCase:
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

    return test_case.model_copy(update={
        "headers": headers,
        "query_params": query_params,
    })


def _resolve_provider(request: TestRunRequest):
    if not request.analyze_failures:
        return None
    try:
        from app.ai.providers import get_llm_provider
        return get_llm_provider(provider_name=request.ai_provider, model=request.ai_model)
    except ValueError:
        try:
            return OpenAIResponsesProvider.from_environment()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


def _run_ai_analysis(results: list[TestExecutionResult], provider: Any) -> tuple[dict | None, str | None]:
    if provider is not None and any(
        result.outcome in {ExecutionOutcome.FAILED, ExecutionOutcome.ERROR}
        for result in results
    ):
        try:
            return analyze_failures(results, provider=provider).model_dump(mode="json"), None
        except (RuntimeError, ValueError) as exc:
            logger.warning("AI failure analysis failed: %s", exc, exc_info=True)
            return None, "Execution completed, but AI analysis was unavailable."
    return None, None


@router.post("/run")
def run_tests(request: TestRunRequest) -> dict:
    """Execute a user-selected batch against an explicitly allowlisted target."""
    _validate_run_request(request)
    provider = _resolve_provider(request)

    prepared_cases = [_prepare_test_case(tc, request) for tc in request.test_cases]
    results = execute_batch(
        prepared_cases,
        request.base_url,
        allowed_hosts=request.allowed_hosts,
        concurrency=request.concurrency,
        timeout=request.timeout,
        allow_private_network=request.allow_private_network,
        allow_mutating_methods=request.allow_mutating_methods,
        executor_fn=execute_test_case,
    )

    analysis, analysis_error = _run_ai_analysis(results, provider)
    return {
        "report": build_execution_report(results),
        "analysis": analysis,
        "analysis_error": analysis_error,
    }


@router.post("/run/stream")
def run_tests_stream(request: TestRunRequest):
    """Execute a user-selected batch with real-time Server-Sent Events (SSE) streaming."""
    _validate_run_request(request)
    provider = _resolve_provider(request)

    prepared_cases = [_prepare_test_case(tc, request) for tc in request.test_cases]

    def event_stream():
        completed_results: list[tuple[int, TestExecutionResult]] = []
        total = len(prepared_cases)

        for idx, result in execute_batch_stream(
            prepared_cases,
            request.base_url,
            allowed_hosts=request.allowed_hosts,
            concurrency=request.concurrency,
            timeout=request.timeout,
            allow_private_network=request.allow_private_network,
            allow_mutating_methods=request.allow_mutating_methods,
            executor_fn=execute_test_case,
        ):
            completed_results.append((idx, result))
            event_payload = {
                "type": "progress",
                "index": idx,
                "completed": len(completed_results),
                "total": total,
                "result": {
                    "name": result.test_case.name,
                    "method": result.test_case.method,
                    "path": result.test_case.path,
                    "outcome": result.outcome.value,
                    "actual_status": result.actual_status,
                    "duration_ms": result.duration_ms,
                    "error": result.error,
                },
            }
            yield f"data: {json.dumps(event_payload)}\n\n"

        sorted_results = [r for _, r in sorted(completed_results, key=lambda item: item[0])]
        analysis, analysis_error = _run_ai_analysis(sorted_results, provider)
        complete_payload = {
            "type": "complete",
            "report": build_execution_report(sorted_results),
            "analysis": analysis,
            "analysis_error": analysis_error,
        }
        yield f"data: {json.dumps(complete_payload)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
