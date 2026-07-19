"""Tests for verify_source: SSRF protection, unique IDs, provenance signing."""

import json
import pytest
from unittest.mock import patch, MagicMock
from cks_mcp.tools.verify_source import verify_source, UnsafeURLError, _assert_url_is_safe
from cks_mcp.provenance import verify, SIGNATURE_KEY

def test_assert_url_is_safe_allows_public():
    _assert_url_is_safe("https://example.com")

def test_assert_url_is_safe_rejects_private():
    with pytest.raises(UnsafeURLError):
        _assert_url_is_safe("http://127.0.0.1")

def test_assert_url_is_safe_rejects_metadata():
    with pytest.raises(UnsafeURLError):
        _assert_url_is_safe("http://169.254.169.254")

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