"""
ingest_document: fetch a URL, extract entities and relations, and build a
Canonical Knowledge Structure from the result.

Uses the same SSRF/DNS-rebinding protection as verify_source.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import json
import re
from collections import Counter
from typing import Any

import cks
from cks_runtime.runtime import Runtime

from cks_mcp.errors import internal_error
from cks_mcp.tools.verify_source.handler import UnsafeURLError, _safe_request

# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]*>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")
_WHITESPACE_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Crude but deterministic HTML-to-text conversion."""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    text = _ENTITY_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "the", "is", "at", "which", "on", "and", "a", "an", "in", "to", "of", "for",
    "with", "by", "from", "as", "or", "it", "its", "be", "was", "are", "been",
    "this", "that", "not", "but", "they", "we", "you", "he", "she", "has", "have",
    "had", "will", "would", "can", "could", "should", "may", "do", "does", "did",
})
_MIN_KEYWORD_LENGTH = 3
_MAX_KEYWORDS = 20


def _extract_title_and_description(html: str) -> tuple[str | None, str | None]:
    """Extract <title> and <meta name='description'> content."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    desc_match = re.search(
        r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
        html, re.IGNORECASE,
    ) or re.search(
        r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']',
        html, re.IGNORECASE,
    )
    title = title_match.group(1).strip() if title_match else None
    desc = desc_match.group(1).strip() if desc_match else None
    return title, desc


def _extract_keywords(text: str, max_keywords: int = _MAX_KEYWORDS) -> list[str]:
    """Return a list of potential keywords (non-stop-words, min length).

    Uses ``heapq.nlargest`` instead of ``Counter.most_common`` (OPT-07):
    both are O(N log N) in the worst case, but ``nlargest`` avoids
    sorting the *entire* counter when only the top-K items are needed —
    making it measurably faster on long texts with large vocabularies.
    """
    words = re.findall(rf"\b[a-zA-Z]{{{_MIN_KEYWORD_LENGTH},}}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counter = Counter(filtered)
    return [word for word, _ in heapq.nlargest(max_keywords, counter.items(), key=lambda x: x[1])]


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def ingest_document(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch a URL, extract entities (title, description, keywords, links) and
    return a Knowledge Structure representing the document.
    """
    url = arguments.get("url")
    if not url:
        return {"error": "missing_parameter", "message": "Missing required parameter: 'url'."}

    # ---- Fetch the page, safely ---------------------------------------------
    # _safe_request (shared with verify_source) resolves and validates
    # the hostname, then pins the connection to one of the validated
    # IPs for the actual request, and manually re-validates each
    # redirect hop before following it -- unlike a bare
    # `requests.get(url, allow_redirects=True)`, which would let a
    # malicious server redirect straight past the SSRF check to an
    # internal/metadata endpoint after the initial URL was found safe,
    # and would re-resolve DNS itself with no pinning, reopening a
    # DNS-rebinding window between the check and the request. A
    # blocking network call (DNS + HTTP GET, up to a 10s timeout per
    # hop), dispatched to a worker thread so it can't stall the event
    # loop.
    def _fetch() -> str:
        resp = _safe_request(url, method="GET", timeout=10)
        if resp is None:
            raise RuntimeError("could not connect to any resolved address")
        resp.raise_for_status()
        return resp.text

    try:
        html = await asyncio.to_thread(_fetch)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": f"Refusing to fetch '{url}': {exc}",
        }
    except Exception as exc:
        return internal_error(f"Failed to fetch URL: {exc}")

    # ---- Extract metadata ---------------------------------------------------
    title, description = _extract_title_and_description(html)
    # Cap HTML before conversion: title/description/keywords only need a
    # fraction of a large page.  Processing megabytes of HTML just to take
    # [:500] of the resulting plain text wastes CPU and memory (OPT-06).
    plain_text = _html_to_text(html[:200_000])
    keywords = _extract_keywords(plain_text)

    # ---- Build Knowledge Structure -----------------------------------------
    # BUG-02 fix: the old `re.sub(...)[:50]` sliced the *substituted*
    # string, so two URLs that differ only after their first ~43 raw
    # characters (e.g. same domain + long path, differing only in the
    # last segment) produced identical doc_id values and caused a
    # "Duplicate canonical identity" error when both were added to the
    # same session.
    #
    # Fix: use a 12-character SHA-256 prefix of the *full* URL as the
    # uniqueness-bearing suffix, and keep only a short human-readable
    # prefix from the sanitised URL for debuggability.  The hash is
    # computed over the original URL bytes (not the sanitised form) so
    # any two distinct URLs are guaranteed to produce different doc_ids
    # with overwhelming probability (2^-48 collision chance per pair).
    _url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    _safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:30]
    doc_id = f"doc-{_safe_prefix}-{_url_hash}"
    objects = []
    relations = []

    # Document object
    doc_structure = {"url": url, "content_preview": plain_text[:500]}
    if title:
        doc_structure["title"] = title
    if description:
        doc_structure["description"] = description

    objects.append({
        "identity": {"id": doc_id, "type": "Document", "name": title or url},
        "structure": doc_structure,
    })

    # Keyword objects + relations
    for i, keyword in enumerate(keywords):
        kw_id = f"{doc_id}-kw-{i}"
        objects.append({
            "identity": {"id": kw_id, "type": "Topic", "name": keyword},
            "structure": {},
        })
        relations.append({
            "identity": {"id": f"rel-{doc_id}-kw-{i}", "type": "Relation", "name": "mentions"},
            "structure": {
                "participants": [doc_id, kw_id],
                "relation_type": "mentions",
            },
        })

    # Объединяем объекты и отношения в один список для CKS
    all_objects = objects + relations
    structure_json = json.dumps({"objects": all_objects})
    try:
        structure = cks.parse(structure_json)
    except cks.SerializationError as exc:
        return internal_error(f"Failed to build Knowledge Structure: {exc}")

    # Serialize for response
    serialized = runtime.core_bridge.serialize(structure)
    return {
        "url": url,
        "title": title,
        "keywords": keywords,
        "knowledge_structure": serialized,
        "object_count": len(structure.objects),
        "relation_count": len(structure.relations()),
    }