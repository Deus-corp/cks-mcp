"""
External source adapters for the Enrichment Agent.

Unlike ``ingest_document`` (fetch one URL a caller already picked),
these adapters take a *query* and call an external search API to
discover candidate URLs -- the actual "search" half of "search ->
filter -> ingest -> link". Each adapter is isolated: one adapter's API
being down or returning something unparseable must not stop the
others from contributing candidates, so failures are caught and
reported per-adapter rather than raised.

Candidates are returned unfetched/unfiltered -- ``score_candidate``
(scoring.py) and ``EnrichmentPolicy``/``is_low_value_enrichment_url``
(filters.py) run on the result before anything is spent on
``ingest_document``.

Adapters implemented: Wikipedia (``opensearch`` API), arXiv (Atom API).
PubMed is a planned follow-up (see ROADMAP.md) -- not implemented here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus

from cks_mcp.tools.verify_source.handler import _safe_request

_TIMEOUT_SECONDS = 10
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(slots=True)
class EnrichmentCandidate:
    url: str
    title: str
    source_adapter: str
    source_kind: str


def _wikipedia_candidates(query: str, limit: int) -> list[EnrichmentCandidate]:
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&format=json&namespace=0&limit={int(limit)}"
        f"&search={quote_plus(query)}"
    )
    resp = _safe_request(url, method="GET", timeout=_TIMEOUT_SECONDS)
    if resp is None:
        raise RuntimeError("Wikipedia opensearch API unreachable")
    resp.raise_for_status()
    parsed = resp.json()
    if not (isinstance(parsed, list) and len(parsed) >= 4):
        raise RuntimeError(f"unexpected Wikipedia opensearch response shape: {parsed!r}")

    titles, _descriptions, urls = parsed[1], parsed[2], parsed[3]
    candidates: list[EnrichmentCandidate] = []
    for title, page_url in zip(titles, urls):
        if not page_url:
            continue
        candidates.append(
            EnrichmentCandidate(
                url=page_url, title=title, source_adapter="wikipedia", source_kind="wikipedia_article"
            )
        )
    return candidates


def _arxiv_candidates(query: str, limit: int) -> list[EnrichmentCandidate]:
    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query={quote_plus('all:' + query)}&start=0&max_results={int(limit)}"
    )
    resp = _safe_request(url, method="GET", timeout=_TIMEOUT_SECONDS)
    if resp is None:
        raise RuntimeError("arXiv API unreachable")
    resp.raise_for_status()

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise RuntimeError(f"could not parse arXiv Atom response: {exc}") from exc

    candidates: list[EnrichmentCandidate] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        id_el = entry.find("atom:id", _ATOM_NS)
        title_el = entry.find("atom:title", _ATOM_NS)
        if id_el is None:
            continue
        text = id_el.text or ""
        if not text.strip():
            continue
        # arXiv Atom <id> is already the abstract-page URL
        # (http://arxiv.org/abs/XXXX.YYYYY) -- real HTML ingest_document
        # can parse, not the raw API query URL itself.
        candidate_url = text.strip().replace("http://", "https://", 1)
        title = (title_el.text or "").strip() if title_el is not None else ""
        candidates.append(
            EnrichmentCandidate(
                url=candidate_url, title=title, source_adapter="arxiv", source_kind="arxiv_abstract"
            )
        )
    return candidates


_ADAPTERS: dict[str, Callable[[str, int], list[EnrichmentCandidate]]] = {
    "wikipedia": _wikipedia_candidates,
    "arxiv": _arxiv_candidates,
}

DEFAULT_ADAPTERS = ("wikipedia", "arxiv")


def build_enrichment_candidates(
    query: str,
    *,
    adapters: tuple[str, ...] = DEFAULT_ADAPTERS,
    limit_per_adapter: int = 3,
) -> tuple[list[EnrichmentCandidate], dict[str, str]]:
    """
    Query every adapter in ``adapters`` for candidates, in-process
    (synchronous, blocking network calls via ``_safe_request`` -- run
    via ``asyncio.to_thread`` from async callers, same convention as
    ``ingest_document``'s own fetch).

    Returns ``(candidates, adapter_errors)``. ``adapter_errors`` maps
    adapter name -> error message for any adapter that raised, so a
    caller can tell "genuinely nothing relevant" apart from "half the
    adapters were down" without every adapter failure aborting the
    whole search.
    """
    query = " ".join(str(query or "").split())
    if not query:
        return [], {}

    candidates: list[EnrichmentCandidate] = []
    errors: dict[str, str] = {}

    for name in adapters:
        adapter_fn = _ADAPTERS.get(name)
        if adapter_fn is None:
            errors[name] = f"unknown adapter: {name!r}"
            continue
        try:
            candidates.extend(adapter_fn(query, limit_per_adapter))
        except Exception as exc:  # noqa: BLE001 -- one adapter's failure must not sink the others
            errors[name] = str(exc)

    return candidates, errors