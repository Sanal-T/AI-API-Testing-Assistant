"""Server-owned target restrictions for the unauthenticated web API."""

import os
from urllib.parse import urlsplit

from fastapi import HTTPException


def validate_server_target_policy(
    base_url: str,
    requested_allowed_hosts: set[str],
    allow_private_network: bool,
) -> set[str]:
    """Restrict request-supplied target choices to operator configuration."""
    configured = {
        host.strip().strip("[]").rstrip(".").lower()
        for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Target execution is disabled until the server ALLOWED_HOSTS setting is configured.",
        )

    requested = {host.strip().strip("[]").rstrip(".").lower() for host in requested_allowed_hosts}
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname not in configured or hostname not in requested:
        raise HTTPException(status_code=403, detail="Target host is not permitted by the server policy.")

    if not requested.issubset(configured):
        raise HTTPException(status_code=403, detail="allowed_hosts cannot exceed the server ALLOWED_HOSTS policy.")

    private_enabled = os.environ.get("ALLOW_PRIVATE_NETWORK_TARGETS", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if allow_private_network and not private_enabled:
        raise HTTPException(
            status_code=403,
            detail="Private-network targets are disabled by server policy.",
        )
    return requested
