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
from requests.adapters import HTTPAdapter

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


def _resolve_and_validate_host(url: str) -> tuple[str, str]:
    """
    Проверяет безопасность URL и возвращает (hostname, verified_ip).
    Выполняет резолвинг единожды, чтобы избежать DNS rebinding.
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

    resolved_ips = {sockaddr[0] for *_, sockaddr in addrinfo}
    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise UnsafeURLError(
            f"URL host '{hostname}' resolves to a non-public address "
            f"({', '.join(sorted(resolved_ips))}); refusing to fetch."
        )
    
    # Возвращаем первый публичный IP для закрепления
    return hostname, list(resolved_ips)[0]


class PinnedHTTPAdapter(HTTPAdapter):
    """HTTPAdapter, который закрепляет соединение за конкретным IP-адресом."""
    def __init__(self, pinned_ip: str, *args, **kwargs):
        self.pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        # Подменяем пул соединений, чтобы запрос шел на проверенный IP
        conn_pool = self.get_connection_with_tls_context(
            request, verify=True, cert=self.cert
        )
        conn_pool.host = self.pinned_ip
        return super().send(request, **kwargs)
    
    def get_connection_with_tls_context(self, request, verify, cert=None):
        return super().get_connection_with_tls_context(request, verify, cert=cert)


def _safe_head_status(url: str) -> int | None:
    """
    Выполняет HEAD-запрос с защитой от DNS rebinding.
    Проверка безопасности и резолвинг IP происходят один раз перед запросом.
    """
    try:
        hostname, verified_ip = _resolve_and_validate_host(url)
    except UnsafeURLError:
        raise  # Перебрасываем исключение для обработки в verify_source

    session = requests.Session()
    adapter = PinnedHTTPAdapter(pinned_ip=verified_ip)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            resp = session.head(url, timeout=_TIMEOUT_SECONDS, allow_redirects=False)
        except requests.RequestException:
            return None

        if resp.is_redirect and resp.headers.get("Location"):
            new_url = urljoin(url, resp.headers["Location"])
            try:
                # Проверяем безопасность нового URL и закрепляем новый IP
                hostname, verified_ip = _resolve_and_validate_host(new_url)
                adapter.pinned_ip = verified_ip
                url = new_url
            except UnsafeURLError:
                # Если редирект ведёт на небезопасный адрес, прерываем проверку
                return None
            continue
        return resp.status_code

    return None


def verify_source(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments["url"]
    subject_id = arguments["subject_id"]

    try:
        _resolve_and_validate_host(url)  # Быстрая предварительная проверка
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": (
                f"Refusing to verify '{url}': {exc} No VerificationRecord "
                f"was created."
            ),
        }

    try:
        status = _safe_head_status(url)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": (
                f"Refusing to verify '{url}': {exc} No VerificationRecord "
                f"was created."
            ),
        }

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