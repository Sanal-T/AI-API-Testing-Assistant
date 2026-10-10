from collections.abc import Generator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import re
import socket
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.models.execution_result import (
    ExecutionErrorKind,
    ExecutionOutcome,
    TestExecutionResult,
)
from app.constants import (
    BLOCKED_REQUEST_HEADERS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MUTATING_METHODS,
    SENSITIVE_RESPONSE_HEADERS,
)
from app.executor.contract_validator import validate_response_contract
from app.models.test_case import TestCase

_MUTATING_METHODS = MUTATING_METHODS
_BLOCKED_REQUEST_HEADERS = BLOCKED_REQUEST_HEADERS
_SENSITIVE_RESPONSE_HEADERS = SENSITIVE_RESPONSE_HEADERS


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def execute_test_case(
    test_case: TestCase,
    base_url: str,
    *,
    allowed_hosts: set[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_private_network: bool = False,
    allow_mutating_methods: bool = False,
) -> TestExecutionResult:
    """Execute one test case against an explicitly configured target URL.

    The target hostname must be explicitly allowlisted. Private/local destinations
    and state-changing methods require separate opt-ins. This function is never
    called by the upload workflow.
    """
    if not base_url:
        raise ValueError("An explicit target base URL is required.")
    if timeout <= 0 or timeout > 60:
        raise ValueError("timeout must be greater than 0 and no more than 60 seconds.")

    method = test_case.method.upper()
    if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError(f"Unsupported HTTP method: {method}")
    if method in _MUTATING_METHODS and not allow_mutating_methods:
        raise ValueError(
            f"{method} requests require allow_mutating_methods=True."
        )

    url = _build_request_url(base_url, test_case.path, test_case.path_params, test_case.query_params)
    _validate_target_url(
        url,
        allowed_hosts=allowed_hosts,
        allow_private_network=allow_private_network,
    )

    headers = _build_request_headers(test_case.headers, has_body=test_case.body is not None)
    body = None if test_case.body is None else json.dumps(test_case.body).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    opener = build_opener(_NoRedirectHandler())

    started = perf_counter()
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        # urllib represents non-2xx responses as HTTPError; they are still
        # actual HTTP responses and should be evaluated against the assertion.
        response = exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        error_kind = (
            ExecutionErrorKind.TIMEOUT
            if isinstance(exc, (TimeoutError, socket.timeout))
            or isinstance(reason, (TimeoutError, socket.timeout))
            else ExecutionErrorKind.NETWORK
        )
        return TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.ERROR,
            actual_status=None,
            response_headers={},
            response_body=None,
            duration_ms=(perf_counter() - started) * 1000,
            error_kind=error_kind,
            error=str(reason),
        )

    with response:
        response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        truncated = len(response_bytes) > MAX_RESPONSE_BYTES
        response_bytes = response_bytes[:MAX_RESPONSE_BYTES]
        status = response.status
        response_headers = _safe_response_headers(response.headers)

    duration_ms = (perf_counter() - started) * 1000
    response_body_text = response_bytes.decode("utf-8", errors="replace")

    contract_result = validate_response_contract(
        test_case=test_case,
        status_code=status,
        response_headers=response_headers,
        response_body_str=response_body_text,
        duration_ms=duration_ms,
    )

    expected = test_case.expected_status
    status_passed = expected is not None and status in expected
    status_unverified = expected is None

    if not status_unverified and not status_passed:
        outcome = ExecutionOutcome.FAILED
        error_msg = f"Expected status {expected}, but received {status}."
        if contract_result.all_errors:
            error_msg += f" {'; '.join(contract_result.all_errors)}"
    elif not contract_result.is_valid:
        outcome = ExecutionOutcome.FAILED
        error_msg = "; ".join(contract_result.all_errors)
    elif status_unverified:
        outcome = ExecutionOutcome.UNVERIFIED
        error_msg = None
    else:
        outcome = ExecutionOutcome.PASSED
        error_msg = None

    return TestExecutionResult(
        test_case=test_case,
        outcome=outcome,
        actual_status=status,
        response_headers=response_headers,
        response_body=response_body_text,
        duration_ms=duration_ms,
        response_truncated=truncated,
        error=error_msg,
        schema_validation_passed=contract_result.schema_passed,
        schema_validation_errors=contract_result.schema_errors,
        header_validation_errors=contract_result.header_errors,
        assertion_errors=contract_result.assertion_errors,
        sla_exceeded=contract_result.sla_exceeded,
    )


def _safe_execute_test_case(
    test_case: TestCase,
    base_url: str,
    *,
    allowed_hosts: set[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_private_network: bool = False,
    allow_mutating_methods: bool = False,
    executor_fn: Any = None,
) -> TestExecutionResult:
    fn = executor_fn or execute_test_case
    try:
        return fn(
            test_case,
            base_url,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
            allow_private_network=allow_private_network,
            allow_mutating_methods=allow_mutating_methods,
        )
    except ValueError as exc:
        return TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.ERROR,
            duration_ms=0,
            error="Request was not sent because target validation failed.",
        )
    except Exception as exc:
        return TestExecutionResult(
            test_case=test_case,
            outcome=ExecutionOutcome.ERROR,
            duration_ms=0,
            error=f"Execution error: {exc}",
        )


def execute_batch(
    test_cases: Sequence[TestCase],
    base_url: str,
    *,
    allowed_hosts: set[str],
    concurrency: int = 5,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_private_network: bool = False,
    allow_mutating_methods: bool = False,
    executor_fn: Any = None,
) -> list[TestExecutionResult]:
    """Execute a batch of test cases concurrently while preserving input order."""
    if not test_cases:
        return []

    if concurrency <= 1 or len(test_cases) == 1:
        return [
            _safe_execute_test_case(
                tc,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
                executor_fn=executor_fn,
            )
            for tc in test_cases
        ]

    max_workers = max(1, min(concurrency, len(test_cases)))
    indexed_results: list[tuple[int, TestExecutionResult]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _safe_execute_test_case,
                tc,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
                executor_fn=executor_fn,
            ): idx
            for idx, tc in enumerate(test_cases)
        }
        for future in as_completed(futures):
            idx = futures[future]
            indexed_results.append((idx, future.result()))

    indexed_results.sort(key=lambda item: item[0])
    return [res for _, res in indexed_results]


def execute_batch_stream(
    test_cases: Sequence[TestCase],
    base_url: str,
    *,
    allowed_hosts: set[str],
    concurrency: int = 5,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_private_network: bool = False,
    allow_mutating_methods: bool = False,
    executor_fn: Any = None,
) -> Generator[tuple[int, TestExecutionResult], None, None]:
    """Execute test cases concurrently and yield (index, result) as each finishes."""
    if not test_cases:
        return

    if concurrency <= 1 or len(test_cases) == 1:
        for idx, tc in enumerate(test_cases):
            res = _safe_execute_test_case(
                tc,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
                executor_fn=executor_fn,
            )
            yield idx, res
        return

    max_workers = max(1, min(concurrency, len(test_cases)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _safe_execute_test_case,
                tc,
                base_url,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                allow_private_network=allow_private_network,
                allow_mutating_methods=allow_mutating_methods,
                executor_fn=executor_fn,
            ): idx
            for idx, tc in enumerate(test_cases)
        }
        for future in as_completed(futures):
            idx = futures[future]
            yield idx, future.result()


def _build_request_url(
    base_url: str,
    path: str,
    path_params: dict[str, Any],
    query_params: dict[str, Any],
) -> str:
    base = urlsplit(base_url)
    if base.scheme.lower() not in {"http", "https"} or not base.netloc:
        raise ValueError("Target base URL must be an absolute http or https URL.")
    if base.username or base.password or base.query or base.fragment:
        raise ValueError("Target base URL cannot contain credentials, a query, or a fragment.")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Test-case path must be an absolute API path beginning with one slash.")

    def replace_parameter(match: re.Match[str]) -> str:
        parameter_name = match.group(1)
        if parameter_name not in path_params:
            raise ValueError(f"Missing path parameter: {parameter_name}")
        return quote(str(path_params[parameter_name]), safe="")

    endpoint_path = re.sub(r"\{([^{}]+)\}", replace_parameter, path)
    if "{" in endpoint_path or "}" in endpoint_path or "?" in endpoint_path or "#" in endpoint_path:
        raise ValueError("Test-case path contains an unresolved parameter or invalid delimiter.")

    full_path = f"{base.path.rstrip('/')}/{endpoint_path.lstrip('/')}"
    query_string = urlencode(query_params, doseq=True)
    return urlunsplit((base.scheme, base.netloc, full_path, query_string, ""))


def _validate_target_url(
    url: str,
    *,
    allowed_hosts: set[str],
    allow_private_network: bool,
) -> None:
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise ValueError("Target URL must include a hostname.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Target URL contains an invalid port.") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("Target URL contains an invalid port.")
    hostname = parsed.hostname.rstrip(".").lower()
    normalized_allowlist = {host.strip("[]").rstrip(".").lower() for host in allowed_hosts}
    if hostname not in normalized_allowlist:
        raise ValueError("Target hostname is not in the configured allowlist.")
    if allow_private_network:
        return
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local and internal targets require allow_private_network=True.")

    try:
        address = ipaddress.ip_address(hostname)
        addresses = {address}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(result[4][0].split("%")[0])
                for result in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise ValueError(f"Target hostname could not be resolved safely: {hostname}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private, loopback, link-local, and reserved targets require allow_private_network=True.")


def _build_request_headers(headers: dict[str, Any], *, has_body: bool) -> dict[str, str]:
    result = {}
    for name, value in headers.items():
        normalized_name = str(name).lower()
        if normalized_name in _BLOCKED_REQUEST_HEADERS:
            raise ValueError(f"The {name} request header is controlled by the executor.")
        header_value = str(value)
        if "\r" in str(name) or "\n" in str(name) or "\r" in header_value or "\n" in header_value:
            raise ValueError("Request headers cannot contain line breaks.")
        result[str(name)] = header_value
    if has_body and not any(name.lower() == "content-type" for name in result):
        result["Content-Type"] = "application/json"
    return result


def _safe_response_headers(headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in _SENSITIVE_RESPONSE_HEADERS
    }
