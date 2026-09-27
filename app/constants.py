"""Centralized constants for HTTP methods, blocked headers, and execution limits."""

MUTATING_METHODS: set[str] = {"POST", "PUT", "PATCH", "DELETE"}
SUPPORTED_METHODS: set[str] = {"GET", "HEAD", "OPTIONS", *MUTATING_METHODS}

BLOCKED_REQUEST_HEADERS: set[str] = {"host", "content-length", "transfer-encoding"}
SENSITIVE_RESPONSE_HEADERS: set[str] = {"authorization", "proxy-authenticate", "set-cookie"}

MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5 MiB
MAX_RESPONSE_BYTES: int = 1_000_000     # 1 MB
DEFAULT_TIMEOUT_SECONDS: float = 10.0
