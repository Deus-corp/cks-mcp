"""
Tests for verify_source: SSRF protection, unique IDs, provenance signing.
"""

import json
import socket
import pytest
from unittest.mock import patch, MagicMock
from cks_mcp.tools.verify_source import verify_source, UnsafeURLError, _resolve_and_validate_host, _safe_head_status
from cks_mcp.provenance import verify, SIGNATURE_KEY

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
    """Dual-stack hosts must yield IPv4 candidates first -- some
    deployment environments have no functional IPv6 route even when a
    hostname resolves to IPv6 addresses, and this ordering is what
    makes _safe_head_status try a working address before giving up."""
    fake_addrinfo = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:4860:4860::8888", 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:4860:4860::8844", 443, 0, 0)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_addrinfo):
        hostname, ips = _resolve_and_validate_host("https://example.com")
    assert ips == ["93.184.216.34", "2001:4860:4860::8888", "2001:4860:4860::8844"]

def test_resolve_and_validate_deduplicates_ips():
    fake_addrinfo = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("93.184.216.34", 443)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_addrinfo):
        hostname, ips = _resolve_and_validate_host("https://example.com")
    assert ips == ["93.184.216.34"]

def test_safe_head_status_falls_back_to_next_candidate():
    """If the first (preferred) candidate address is unreachable, the
    next validated candidate must still be tried before giving up --
    this is what turns a non-deterministic address-family pick into a
    robust one."""
    with patch(
        "cks_mcp.tools.verify_source._resolve_and_validate_host",
        return_value=("example.com", ["203.0.113.1", "93.184.216.34"]),
    ):
        call_ips = []

        class FakeResponse:
            is_redirect = False
            status_code = 200

        def fake_head(self, url, timeout, allow_redirects):
            import requests
            # Read which IP is currently pinned via the thread-local
            # override installed by pin_dns, to prove the fallback
            # actually advanced to the second candidate.
            from cks_mcp.tools.verify_source import _thread_local
            pinned = _thread_local.dns_overrides.get("example.com")
            call_ips.append(pinned)
            if pinned == "203.0.113.1":
                raise requests.exceptions.ConnectionError("unreachable")
            return FakeResponse()

        with patch("requests.Session.head", fake_head):
            status = _safe_head_status("https://example.com")

    assert status == 200
    assert call_ips == ["203.0.113.1", "93.184.216.34"]

def test_verify_source_returns_unique_ids():
    with patch("cks_mcp.tools.verify_source._safe_head_status", return_value=200):
        result = verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    ids = [obj["identity"]["id"] for obj in result["objects"]]
    assert len(set(ids)) == len(ids)
    assert all(id.startswith("vr-") or id.startswith("rel-") for id in ids)

def test_verify_source_includes_signature():
    with patch("cks_mcp.tools.verify_source._safe_head_status", return_value=200):
        result = verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    record = result["objects"][0]
    assert SIGNATURE_KEY in record["structure"]

def test_verify_source_signature_verifies():
    with patch("cks_mcp.tools.verify_source._safe_head_status", return_value=200):
        result = verify_source(MagicMock(), {"url": "https://example.com", "subject_id": "doc-1"})
    record = result["objects"][0]
    assert verify(
        record_id=record["identity"]["id"],
        subject_id="doc-1",
        checked_at=record["structure"]["checked_at"],
        checked_via=record["structure"]["checked_via"],
        http_status=record["structure"].get("http_status"),
        signature=record["structure"][SIGNATURE_KEY],
    )

def test_verify_source_rejects_unsafe_url():
    result = verify_source(MagicMock(), {"url": "http://127.0.0.1", "subject_id": "doc-1"})
    assert result["error"] == "unsafe_url"