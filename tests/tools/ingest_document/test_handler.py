"""Unit tests for the ingest_document MCP tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

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

    def fake_safe_request(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "cks_mcp.tools.ingest_document.handler._safe_request", fake_safe_request
    )
    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(2, 1, 6, '', ('93.184.216.34', 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await ingest_document(runtime, {"url": "https://example.com/"})
    assert "knowledge_structure" in result
    assert result["title"] == "Test Title"
    keywords = result["keywords"]
    assert len(keywords) > 0
    assert "canonical" in keywords

    ks = json.loads(result["knowledge_structure"])
    types = {obj["identity"]["type"] for obj in ks["objects"]}
    # Expect at least Document, Topic, Metadata; possibly Section from body text
    assert "Document" in types
    assert "Topic" in types
    assert "Metadata" in types
    relations = [obj for obj in ks["objects"] if obj["identity"]["type"] == "Relation"]
    mention_rels = [r for r in relations if r["structure"]["relation_type"] == "mentions"]
    assert len(mention_rels) == len(keywords)
    assert any(r["structure"]["relation_type"] == "has_metadata" for r in relations)
    # Default section may appear if body text exists, so accept either N+1 or N+2 relations
    assert result["relation_count"] in (len(keywords) + 1, len(keywords) + 2)
    # Object count: Document + N Topics + Metadata (+ Section) + all relations
    assert result["object_count"] >= 2 * len(keywords) + 3


class TestDocIdUnit:
    """Pure-unit tests for doc_id generation (sync, no asyncio needed)."""

    def _make_id(self, url: str) -> str:
        import hashlib
        import re
        _url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        _safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:30]
        return f"doc-{_safe_prefix}-{_url_hash}"

    def test_doc_id_no_collision_for_long_urls(self):
        url1 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page1"
        url2 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page2"
        id1, id2 = self._make_id(url1), self._make_id(url2)
        assert id1 != id2, f"BUG-02 still present: both URLs produce doc_id='{id1}'"

    def test_doc_id_is_deterministic(self):
        url = "https://docs.example.org/api/v2/reference"
        assert self._make_id(url) == self._make_id(url)

    def test_doc_id_contains_only_valid_cks_chars(self):
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
    """End-to-end: ingesting two URLs that would have collided under the old
    scheme must produce two distinct doc_ids."""
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

    assert "knowledge_structure" in result1
    assert "knowledge_structure" in result2

    ks1 = json.loads(result1["knowledge_structure"])
    ks2 = json.loads(result2["knowledge_structure"])
    doc_ids_1 = {o["identity"]["id"] for o in ks1["objects"] if o["identity"]["type"] == "Document"}
    doc_ids_2 = {o["identity"]["id"] for o in ks2["objects"] if o["identity"]["type"] == "Document"}

    assert doc_ids_1.isdisjoint(doc_ids_2), (
        f"BUG-02: both ingests produced the same Document id: "
        f"{doc_ids_1 & doc_ids_2}"
    )


# ---------------------------------------------------------------------------
# New tests for structured extraction (sections, tables, lists, metadata)
# ---------------------------------------------------------------------------

_STRUCTURED_HTML = """\
<html>
<head>
<title>Photosynthesis Basics</title>
<meta name="description" content="An intro to photosynthesis.">
<meta name="author" content="Jane Doe">
<meta property="og:title" content="Photosynthesis Basics (OG)">
<meta property="og:image" content="https://example.com/img.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Photosynthesis Basics",
  "author": {"@type": "Person", "name": "Jane Doe"}
}
</script>
</head>
<body>
<h1>Introduction</h1>
<p>Plants convert light to energy.</p>

<h2>Key Stages</h2>
<p>Two main stages.</p>

<table>
<caption>Stage Comparison</caption>
<tr><th>Stage</th><th>Location</th></tr>
<tr><td>Light reactions</td><td>Thylakoid membrane</td></tr>
</table>

<ul>
<li>Chlorophyll absorbs light</li>
<li>Water is split</li>
</ul>
</body>
</html>
"""

async def test_ingest_structured_content_deterministic(monkeypatch):
    """With use_llm=False (default), the response contains Section, Table, List, Metadata objects."""
    import socket

    from cks_mcp.tools.ingest_document.handler import ingest_document

    runtime = _real_runtime()

    class FakeResponse:
        text = _STRUCTURED_HTML
        status_code = 200
        def raise_for_status(self): pass

    monkeypatch.setattr("cks_mcp.tools.ingest_document.handler._safe_request", lambda *a, **kw: FakeResponse())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))])

    result = await ingest_document(runtime, {"url": "https://example.com/photosynthesis"})
    assert "knowledge_structure" in result
    ks = json.loads(result["knowledge_structure"])
    types = {obj["identity"]["type"] for obj in ks["objects"]}

    # All expected types present
    assert "Document" in types
    assert "Section" in types
    assert "Table" in types
    assert "List" in types
    assert "Metadata" in types

    # Count objects of each type
    doc_objects = [o for o in ks["objects"] if o["identity"]["type"] == "Document"]
    section_objects = [o for o in ks["objects"] if o["identity"]["type"] == "Section"]
    table_objects = [o for o in ks["objects"] if o["identity"]["type"] == "Table"]
    list_objects = [o for o in ks["objects"] if o["identity"]["type"] == "List"]
    meta_objects = [o for o in ks["objects"] if o["identity"]["type"] == "Metadata"]

    assert len(doc_objects) == 1
    # We have two headings -> two sections
    assert len(section_objects) == 2
    assert len(table_objects) == 1
    assert len(list_objects) == 1
    assert len(meta_objects) == 1

    # Relations
    rel_types = {
        rel["structure"]["relation_type"]
        for rel in ks["objects"]
        if rel["identity"]["type"] == "Relation"
    }
    assert "has_section" in rel_types
    assert "has_table" in rel_types
    assert "has_list" in rel_types
    assert "has_metadata" in rel_types


async def test_ingest_structured_with_use_llm(monkeypatch):
    """When use_llm=True, the LLM is called and its output is returned."""
    import socket

    from cks_mcp.tools.ingest_document.handler import ingest_document

    runtime = _real_runtime()

    class FakeResponse:
        text = _STRUCTURED_HTML
        status_code = 200
        def raise_for_status(self): pass

    monkeypatch.setattr("cks_mcp.tools.ingest_document.handler._safe_request", lambda *a, **kw: FakeResponse())
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))])

    # Mock the LLM call at the level of _build_llm_structure
    with patch(
        "cks_mcp.tools.ingest_document.handler._build_llm_structure",
        return_value=(MagicMock(), "test-model"),
    ) as mock_llm:
        result = await ingest_document(
            runtime, {"url": "https://example.com/", "use_llm": True}
        )

    # Verify LLM was invoked and we got a structured response
    mock_llm.assert_called_once()
    assert "knowledge_structure" in result
    assert result.get("model_used") == "test-model"