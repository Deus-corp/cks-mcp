"""Unit tests for the ingest_document MCP tool."""

from __future__ import annotations

import json

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())



async def test_ingest_document_missing_url():
    from cks_mcp.tools.ingest_document.handler import ingest_document
    runtime = _real_runtime()
    result = await ingest_document(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_ingest_document_unsafe_url():
    from cks_mcp.tools.ingest_document.handler import ingest_document
    runtime = _real_runtime()
    result = await ingest_document(runtime, {"url": "http://127.0.0.1/"})
    assert result["error"] == "unsafe_url"


async def test_ingest_document_valid_url(monkeypatch):
    """Simulate a real HTTP response and check the output structure."""
    import socket

    from cks_mcp.tools.ingest_document.handler import ingest_document

    runtime = _real_runtime()

    class FakeResponse:
        text = "<html><head><title>Test Title</title><meta name='description' content='A test page'></head><body><p>knowledge graph structure canonical</p></body></html>"
        status_code = 200
        def raise_for_status(self): pass

    # Мокаем _safe_request, которая теперь используется вместо requests.get
    def fake_safe_request(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "cks_mcp.tools.ingest_document.handler._safe_request", fake_safe_request
    )
    # Также нужно замокать DNS, чтобы _resolve_and_validate_host не упал
    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(2, 1, 6, '', ('93.184.216.34', 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await ingest_document(runtime, {"url": "https://example.com/"})
    assert "knowledge_structure" in result
    assert result["title"] == "Test Title"
    keywords = result["keywords"]
    assert len(keywords) > 0
    assert "canonical" in keywords
    assert result["relation_count"] == len(keywords)
    assert result["object_count"] == 1 + len(keywords) * 2


class TestDocIdUnit:
    """Pure-unit tests for doc_id generation (sync, no asyncio needed)."""

    def _make_id(self, url: str) -> str:
        import hashlib
        import re
        _url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        _safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:30]
        return f"doc-{_safe_prefix}-{_url_hash}"

    def test_doc_id_no_collision_for_long_urls(self):
        """
        BUG-02: the old re.sub(...)[:50] sliced the *substituted* string,
        so two URLs differing only after their ~43rd raw character produced
        identical doc_ids.  The fix adds a 12-char SHA-256 suffix that makes
        every distinct URL yield a distinct id.
        """
        url1 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page1"
        url2 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page2"
        id1, id2 = self._make_id(url1), self._make_id(url2)
        assert id1 != id2, f"BUG-02 still present: both URLs produce doc_id='{id1}'"

    def test_doc_id_is_deterministic(self):
        """Same URL must always produce the same doc_id (no randomness)."""
        url = "https://docs.example.org/api/v2/reference"
        assert self._make_id(url) == self._make_id(url)

    def test_doc_id_contains_only_valid_cks_chars(self):
        """doc_id must only contain characters valid for CKS identity ids."""
        import re
        tricky_urls = [
            "https://example.com/path?q=hello&lang=en#section",
            "https://xn--nxasmq6b.com/日本語",
            "https://example.com/" + "a" * 200,
        ]
        for url in tricky_urls:
            doc_id = self._make_id(url)
            assert re.match(r"^[a-zA-Z0-9_-]+$", doc_id), (
                f"doc_id '{doc_id}' contains invalid characters for URL: {url[:60]}"
            )


async def test_ingest_two_long_urls_no_collision(monkeypatch):
    """
    End-to-end: ingesting two URLs that would have collided under the old
    scheme must produce two distinct doc_ids and not raise
    'Duplicate canonical identity'.
    """
    import socket

    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.ingest_document.handler import ingest_document

    runtime = Runtime(core=CksCoreAdapter())

    class FakeResp:
        text = "<html><title>Page</title><body>content canonical knowledge</body></html>"
        def raise_for_status(self): pass

    monkeypatch.setattr("cks_mcp.tools.ingest_document.handler._safe_request", lambda *a, **kw: FakeResp())
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))])

    url1 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page1"
    url2 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page2"

    result1 = await ingest_document(runtime, {"url": url1})
    result2 = await ingest_document(runtime, {"url": url2})

    assert "knowledge_structure" in result1, f"result1 error: {result1}"
    assert "knowledge_structure" in result2, f"result2 error: {result2}"

    # core_bridge.serialize returns a JSON string; parse it to inspect ids.
    ks1 = json.loads(result1["knowledge_structure"])
    ks2 = json.loads(result2["knowledge_structure"])
    doc_ids_1 = {o["identity"]["id"] for o in ks1["objects"] if o["identity"]["type"] == "Document"}
    doc_ids_2 = {o["identity"]["id"] for o in ks2["objects"] if o["identity"]["type"] == "Document"}

    assert doc_ids_1.isdisjoint(doc_ids_2), (
        f"BUG-02: both ingests produced the same Document id: "
        f"{doc_ids_1 & doc_ids_2}"
    )
