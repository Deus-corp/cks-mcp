"""
Deterministic, no-network-I/O scoring for enrichment candidate URLs.

The point of scoring before ``ingest_document`` is spending: fetching
+ extracting a page (and, with ``use_llm``, an LLM call on top) costs
real time and money, so candidates should be ranked and thresholded
*before* any of that runs, not after. The heuristic below combines
domain authority (is this generally a trustworthy publisher?) and
query relevance (does the URL/title actually relate to what we're
looking for?) into one score in [0, 1].

Adapted from an unrelated internal crawler project's source-scoring
heuristic (domain authority table, weighted combination) -- reworked
here without that project's fixed domain-specific keyword list, since
CKS enrichment isn't scoped to any one topic area. Relevance is scored
by query/candidate term overlap instead, computed fresh per call
against whatever query the caller is enriching.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import unquote_plus, urlparse

HIGH_AUTHORITY_DOMAINS: Mapping[str, float] = {
    "en.wikipedia.org": 0.90,
    "wikipedia.org": 0.88,
    "arxiv.org": 0.92,
    "export.arxiv.org": 0.92,
    "docs.python.org": 0.94,
    "github.com": 0.80,
    "pypi.org": 0.80,
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _authority_score(url: str) -> float:
    host = (urlparse(url).netloc or "").lower().split("@")[-1].split(":")[0]
    if not host:
        return 0.35
    if host in HIGH_AUTHORITY_DOMAINS:
        return HIGH_AUTHORITY_DOMAINS[host]
    for domain, score in HIGH_AUTHORITY_DOMAINS.items():
        if host.endswith(f".{domain}"):
            return max(0.50, score - 0.05)
    if host.endswith(".edu"):
        return 0.80
    if host.endswith(".gov"):
        return 0.84
    if host.endswith(".org"):
        return 0.62
    return 0.50


def _relevance_score(url: str, title: str, query: str) -> float:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.5  # no query to compare against -- neutral, not zero

    parsed = urlparse(url)
    candidate_text = " ".join(
        [unquote_plus(parsed.path or ""), unquote_plus(parsed.query or ""), title or ""]
    )
    candidate_terms = _tokenize(candidate_text)
    if not candidate_terms:
        return 0.3

    overlap = len(query_terms & candidate_terms) / len(query_terms)
    return _clamp01(0.3 + 0.7 * overlap)


def score_candidate(
    url: str,
    *,
    title: str = "",
    query: str = "",
    source_adapter: str = "",
) -> float:
    """
    Score one enrichment candidate in [0, 1], combining domain
    authority (40%) and query relevance (60% -- the whole point is
    finding things *relevant to the gap being filled*, so this
    dominates). ``source_adapter`` is accepted for future adapter-
    specific weighting but doesn't currently change the score --
    authority/relevance already capture what adapter-type scoring
    would add for the adapters this module knows about (arXiv/
    Wikipedia are both already high-authority domains).
    """
    del source_adapter  # reserved, see docstring
    authority = _authority_score(url)
    relevance = _relevance_score(url, title, query)
    return round(_clamp01(0.4 * authority + 0.6 * relevance), 4)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))