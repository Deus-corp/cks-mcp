from __future__ import annotations

from cks_mcp.enrichment.adapters import build_enrichment_candidates


class _FakeResponse:
    def __init__(self, *, json_data=None, text: str = "", status_code: int = 200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Retrieval Augmented Generation for Knowledge Graphs</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.54321v2</id>
    <title>Another Paper</title>
  </entry>
</feed>
"""


def test_wikipedia_adapter_parses_opensearch_response(monkeypatch):
    def fake_safe_request(url, **kwargs):
        assert "wikipedia.org" in url
        return _FakeResponse(
            json_data=[
                "retrieval augmented generation",
                ["Retrieval-augmented generation"],
                [""],
                ["https://en.wikipedia.org/wiki/Retrieval-augmented_generation"],
            ]
        )

    monkeypatch.setattr("cks_mcp.enrichment.adapters._safe_request", fake_safe_request)

    candidates, errors = build_enrichment_candidates(
        "retrieval augmented generation", adapters=("wikipedia",)
    )
    assert errors == {}
    assert len(candidates) == 1
    assert candidates[0].url == "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
    assert candidates[0].source_adapter == "wikipedia"


def test_arxiv_adapter_parses_atom_feed(monkeypatch):
    def fake_safe_request(url, **kwargs):
        assert "export.arxiv.org" in url
        return _FakeResponse(text=_ARXIV_ATOM)

    monkeypatch.setattr("cks_mcp.enrichment.adapters._safe_request", fake_safe_request)

    candidates, errors = build_enrichment_candidates("retrieval augmented generation", adapters=("arxiv",))
    assert errors == {}
    assert len(candidates) == 2
    assert candidates[0].url == "https://arxiv.org/abs/2401.12345v1"  # http -> https
    assert candidates[0].title == "Retrieval Augmented Generation for Knowledge Graphs"
    assert candidates[0].source_adapter == "arxiv"


def test_one_adapter_failing_does_not_block_the_other(monkeypatch):
    def fake_safe_request(url, **kwargs):
        if "wikipedia.org" in url:
            raise RuntimeError("wikipedia is down")
        return _FakeResponse(text=_ARXIV_ATOM)

    monkeypatch.setattr("cks_mcp.enrichment.adapters._safe_request", fake_safe_request)

    candidates, errors = build_enrichment_candidates(
        "retrieval augmented generation", adapters=("wikipedia", "arxiv")
    )
    assert "wikipedia" in errors
    assert "arxiv" not in errors
    assert len(candidates) == 2  # arxiv's two entries still came through


def test_unreachable_returns_error_not_exception(monkeypatch):
    monkeypatch.setattr("cks_mcp.enrichment.adapters._safe_request", lambda url, **kw: None)

    candidates, errors = build_enrichment_candidates("query", adapters=("wikipedia", "arxiv"))
    assert candidates == []
    assert "wikipedia" in errors and "arxiv" in errors


def test_empty_query_returns_nothing_without_calling_adapters(monkeypatch):
    called = []
    monkeypatch.setattr(
        "cks_mcp.enrichment.adapters._safe_request", lambda url, **kw: called.append(url)
    )
    candidates, errors = build_enrichment_candidates("   ", adapters=("wikipedia", "arxiv"))
    assert candidates == []
    assert errors == {}
    assert called == []


def test_unknown_adapter_name_reported_as_error():
    candidates, errors = build_enrichment_candidates("query", adapters=("not_a_real_adapter",))
    assert candidates == []
    assert "not_a_real_adapter" in errors


def test_malformed_wikipedia_response_shape_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(
        "cks_mcp.enrichment.adapters._safe_request",
        lambda url, **kw: _FakeResponse(json_data={"unexpected": "shape"}),
    )
    candidates, errors = build_enrichment_candidates("query", adapters=("wikipedia",))
    assert candidates == []
    assert "wikipedia" in errors


def test_malformed_arxiv_xml_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(
        "cks_mcp.enrichment.adapters._safe_request",
        lambda url, **kw: _FakeResponse(text="<not valid xml"),
    )
    candidates, errors = build_enrichment_candidates("query", adapters=("arxiv",))
    assert candidates == []
    assert "arxiv" in errors