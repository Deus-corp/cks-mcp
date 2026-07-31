"""Tests for verify_source: SSRF protection, unique IDs, provenance signing."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.provenance import SIGNATURE_KEY, verify
from cks_mcp.tools.verify_source.handler import (
    UnsafeURLError,
    _resolve_and_validate_host,
    _safe_head_status,
    verify_source,
)


def test_resolve_and_validate_allows_public():
    hostname, ips = _resolve_and_validate_host("https://example.com")
    assert hostname == "example.com"
    assert isinstance(ips, list)
    assert len(ips) > 0

def test_resolve_and_validate_rejects_private():
    with pytest.raises(UnsafeURLError):
        _resolve_and_validate_host("http://127.0.0.1")

def test_resolve_and_validate_rejects_metadata():
    with pytest.raises(UnsafeURLError):
        _resolve_and_validate_host("http://169.254.169.254")

def test_resolve_and_validate_orders_ipv4_before_ipv6():
    fake_addrinfo = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:4860:4860::8888", 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:4860:4860::8844", 443, 0, 0)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_addrinfo):
        _hostname, ips = _resolve_and_validate_host("https://example.com")
    assert ips == ["93.184.216.34", "2001:4860:4860::8888", "2001:4860:4860::8844"]

def test_resolve_and_validate_deduplicates_ips():
    fake_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("93.184.216.34", 443)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_addrinfo):
        _hostname, ips = _resolve_and_validate_host("https://example.com")
    assert ips == ["93.184.216.34"]

def test_safe_head_status_falls_back_to_next_candidate():
    with patch(
        "cks_mcp.tools.verify_source.handler._resolve_and_validate_host",
        return_value=("example.com", ["203.0.113.1", "93.184.216.34"]),
    ):
        call_ips = []

        class FakeResponse:
            is_redirect = False
            status_code = 200

        def fake_head(self, url, timeout, allow_redirects):
            import requests

            from cks_mcp.tools.verify_source.handler import _thread_local
            pinned = _thread_local.dns_overrides.get("example.com")
            call_ips.append(pinned)
            if pinned == "203.0.113.1":
                raise requests.exceptions.ConnectionError("unreachable")
            return FakeResponse()

        with patch("requests.Session.head", fake_head):
            status = _safe_head_status("https://example.com")

    assert status == 200
    assert call_ips == ["203.0.113.1", "93.184.216.34"]

@pytest.mark.asyncio
async def test_verify_source_returns_unique_ids():
    with patch("cks_mcp.tools.verify_source.handler._safe_head_status", return_value=200):
        result = await verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    ids = [obj["identity"]["id"] for obj in result["objects"]]
    assert len(set(ids)) == len(ids)
    assert all(id.startswith(("vr-", "rel-")) for id in ids)

@pytest.mark.asyncio
async def test_verify_source_includes_signature():
    with patch("cks_mcp.tools.verify_source.handler._safe_head_status", return_value=200):
        result = await verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    record = result["objects"][0]
    assert SIGNATURE_KEY in record["structure"]

@pytest.mark.asyncio
async def test_verify_source_signature_verifies():
    with patch("cks_mcp.tools.verify_source.handler._safe_head_status", return_value=200):
        result = await verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    record = result["objects"][0]
    assert verify(
        record_id=record["identity"]["id"],
        subject_id="doc-1",
        checked_at=record["structure"]["checked_at"],
        checked_via=record["structure"]["checked_via"],
        http_status=record["structure"].get("http_status"),
        signature=record["structure"][SIGNATURE_KEY],
    )

@pytest.mark.asyncio
async def test_verify_source_rejects_unsafe_url():
    result = await verify_source(MagicMock(), {"url": "http://127.0.0.1", "subject_id": "doc-1"})
    assert result["error"] == "unsafe_url"