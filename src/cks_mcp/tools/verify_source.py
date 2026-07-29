"""
verify_source: perform a real HTTP check against an external URL and
build a signed VerificationRecord from the *actual* result.

DNS rebinding protection is implemented by temporarily overriding
``socket.getaddrinfo`` on a per-thread basis, so that the HTTP
request is pinned to the specific IP address resolved during the
safety check. This preserves SNI and SSL certificate validation,
unlike connection-pool mutation.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests
from cks_runtime.runtime import Runtime

from cks_mcp.provenance import SIGNATURE_KEY, sign

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_REDIRECTS = 3
_TIMEOUT_SECONDS = 5


class UnsafeURLError(ValueError):
    """Raised when a URL is not a safe target for an outbound request."""

# Python's ipaddress module does not classify these ranges as
# is_private/is_reserved/etc, but they are not globally-routable
# public internet addresses either, and are used in real deployments
# for internal/inter-node addressing -- most notably 100.64.0.0/10
# (RFC 6598 "Shared Address Space"), which is exactly the range
# Tailscale and several cloud providers' internal CGNAT-style
# networking assign to nodes/containers. Without this explicit check,
# `_is_public_ip` treats such internal hosts as public and
# `verify_source` will happily issue a real HTTP request to them --
# an SSRF hole into precisely the kind of internal network this
# function exists to keep unreachable.
_EXTRA_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "100.64.0.0/10",  # RFC 6598 Shared Address Space (CGNAT, Tailscale, ...)
        "192.0.0.0/24",  # RFC 6890 IETF Protocol Assignments
    )
)


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if any(ip in network for network in _EXTRA_BLOCKED_NETWORKS):
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


# ---------------------------------------------------------------------------
# DNS rebinding protection via thread-local getaddrinfo override
# ---------------------------------------------------------------------------

# DNS rebinding protection via temporary, thread-local getaddrinfo override
_orig_getaddrinfo = socket.getaddrinfo
_thread_local = threading.local()

# Reference-counted activation guard. socket.getaddrinfo is a single,
# process-wide attribute: if two pin_dns() contexts are open on
# different threads at once, a naive "save on entry / restore on exit"
# pattern is unsafe -- whichever context exits first restores whatever
# IT saw on entry, which can be the *other* thread's patched function,
# silently reverting socket.getaddrinfo to the real, unpinned resolver
# while that other thread still believes it is protected. That
# reopens exactly the DNS-rebinding window this code exists to close.
# Counting active contexts under a lock instead means the patch is
# installed once (by the first context to open) and removed once (by
# the last context to close), regardless of interleaving.
_patch_lock = threading.Lock()
_active_patches = 0


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    overrides = getattr(_thread_local, "dns_overrides", {})
    if host in overrides:
        host = overrides[host]
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


@contextmanager
def pin_dns(hostname: str, ip: str):
    """Temporarily pin a hostname to a specific IP for the duration of the context."""
    global _active_patches
    if not hasattr(_thread_local, "dns_overrides"):
        _thread_local.dns_overrides = {}
    old_ip = _thread_local.dns_overrides.get(hostname)
    _thread_local.dns_overrides[hostname] = ip
    with _patch_lock:
        _active_patches += 1
        if _active_patches == 1:
            socket.getaddrinfo = _patched_getaddrinfo
    try:
        yield
    finally:
        with _patch_lock:
            _active_patches -= 1
            if _active_patches == 0:
                socket.getaddrinfo = _orig_getaddrinfo
        if old_ip is None:
            del _thread_local.dns_overrides[hostname]
        else:
            _thread_local.dns_overrides[hostname] = old_ip


# ---------------------------------------------------------------------------


def _resolve_and_validate_host(url: str) -> tuple[str, list[str]]:
    """
    Resolve and validate `url`'s hostname, returning the hostname and
    an ordered list of validated, public candidate IPs -- IPv4
    addresses first. Preferring IPv4 and trying multiple candidates
    (see _safe_head_status) avoids committing to a single,
    arbitrarily-chosen address that may belong to an address family
    with no functional outbound route in the deployment environment.
    """
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

    seen: set[str] = set()
    ipv4: list[str] = []
    ipv6: list[str] = []
    for family, _, _, _, sockaddr in addrinfo:
        ip = str(sockaddr[0])
        if ip in seen:
            continue
        seen.add(ip)
        (ipv4 if family == socket.AF_INET else ipv6).append(ip)
    resolved_ips = ipv4 + ipv6

    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise UnsafeURLError(
            f"URL host '{hostname}' resolves to a non-public address "
            f"({', '.join(sorted(seen))}); refusing to fetch."
        )

    return hostname, resolved_ips


def _safe_head_status(url: str) -> int | None:
    try:
        hostname, candidate_ips = _resolve_and_validate_host(url)
    except UnsafeURLError as e:
        raise UnsafeURLError(str(e)) from e

    session = requests.Session()

    for _ in range(_MAX_REDIRECTS + 1):
        resp = None
        for ip in candidate_ips:
            with pin_dns(hostname, ip):
                try:
                    resp = session.head(
                        url, timeout=_TIMEOUT_SECONDS, allow_redirects=False
                    )
                    break
                except requests.RequestException:
                    # This specific candidate address didn't work --
                    # try the next validated one (e.g. IPv4 after an
                    # unreachable IPv6 address) before giving up.
                    continue

        if resp is None:
            return None

        if resp.is_redirect and resp.headers.get("Location"):
            new_url = urljoin(url, resp.headers["Location"])
            try:
                hostname, candidate_ips = _resolve_and_validate_host(new_url)
                url = new_url
            except UnsafeURLError:
                return None
            continue
        return resp.status_code

    return None


def verify_source(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments["url"]
    subject_id = arguments["subject_id"]

    try:
        _resolve_and_validate_host(url)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": (
                f"Refusing to verify '{url}': {exc} No VerificationRecord was created."
            ),
        }

    try:
        status = _safe_head_status(url)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": (
                f"Refusing to verify '{url}': {exc} No VerificationRecord was created."
            ),
        }

    checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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
                "identity": {
                    "id": record_id,
                    "type": "VerificationRecord",
                    "name": "verification",
                },
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
