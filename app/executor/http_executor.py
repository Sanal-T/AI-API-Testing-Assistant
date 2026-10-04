from dataclasses import dataclass
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

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
