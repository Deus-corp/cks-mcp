"""
verify_source: perform a real HTTP check against an external URL and
build a signed VerificationRecord from the *actual* result.
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests

from cks_runtime.runtime import Runtime
from cks_mcp.provenance import sign, SIGNATURE_KEY

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_REDIRECTS = 3
_TIMEOUT_SECONDS = 5


class UnsafeURLError(ValueError):
    """Raised when a URL is not a safe target for an outbound request."""


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _assert_url_is_safe(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only http/https are allowed."
        )
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname.")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{hostname}': {exc}") from exc

    resolved_ips = {sockaddr[0] for *_, sockaddr in addrinfo}
    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise UnsafeURLError(
            f"URL host '{hostname}' resolves to a non-public address "
            f"({', '.join(sorted(resolved_ips))}); refusing to fetch."
        )


def _safe_head_status(url: str) -> int | None:
    for _ in range(_MAX_REDIRECTS + 1):
        _assert_url_is_safe(url)
        try:
            resp = requests.head(url, timeout=_TIMEOUT_SECONDS, allow_redirects=False)
        except requests.RequestException:
            return None

        if resp.is_redirect and resp.headers.get("Location"):
            url = urljoin(url, resp.headers["Location"])
            continue
        return resp.status_code

    return None


def verify_source(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments["url"]
    subject_id = arguments["subject_id"]

    try:
        _assert_url_is_safe(url)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": (
                f"Refusing to verify '{url}': {exc} No VerificationRecord "
                f"was created."
            ),
        }

    status = _safe_head_status(url)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checked_via = "automated_http_check"

    record_id = f"vr-{uuid4().hex}"
    relation_id = f"rel-{uuid4().hex}"

    signature = sign(
        record_id=record_id,
        subject_id=subject_id,
        checked_at=checked_at,
        checked_via=checked_via,
        http_status=status,
    )

    record_structure: dict[str, Any] = {
        "checked_at": checked_at,
        "checked_via": checked_via,
        SIGNATURE_KEY: signature,
    }
    if status is not None:
        record_structure["http_status"] = status

    return {
        "objects": [
            {
                "identity": {"id": record_id, "type": "VerificationRecord", "name": "verification"},
                "structure": record_structure,
            },
            {
                "identity": {"id": relation_id, "type": "Relation", "name": "r"},
                "structure": {
                    "participants": [subject_id, record_id],
                    "relation_type": "verified_by",
                },
            },
        ]
    }