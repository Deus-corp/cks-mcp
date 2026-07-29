"""
ingest_document: fetch a URL, extract entities and relations, and build a
Canonical Knowledge Structure from the result.

Uses the same SSRF/DNS-rebinding protection as verify_source.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

import cks
from cks_runtime.runtime import Runtime

from cks_mcp.errors import internal_error
from cks_mcp.tools.verify_source import (
    UnsafeURLError,
    _resolve_and_validate_host,
)

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
    """Return a list of potential keywords (non-stop-words, min length)."""
    words = re.findall(rf"\b[a-zA-Z]{{{_MIN_KEYWORD_LENGTH},}}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counter = Counter(filtered)
    return [word for word, _ in counter.most_common(max_keywords)]


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def ingest_document(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch a URL, extract entities (title, description, keywords, links) and
    return a Knowledge Structure representing the document.
    """
    url = arguments.get("url")
    if not url:
        return {"error": "missing_parameter", "message": "Missing required parameter: 'url'."}

    # ---- SSRF protection ---------------------------------------------------
    try:
        _resolve_and_validate_host(url)
    except UnsafeURLError as exc:
        return {
            "error": "unsafe_url",
            "message": f"Refusing to fetch '{url}': {exc}",
        }

    # ---- Fetch the page ----------------------------------------------------
    try:
        import requests
        resp = requests.get(url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        return internal_error(f"Failed to fetch URL: {exc}")

    # ---- Extract metadata ---------------------------------------------------
    title, description = _extract_title_and_description(html)
    plain_text = _html_to_text(html)
    keywords = _extract_keywords(plain_text)

    # ---- Build Knowledge Structure -----------------------------------------
    doc_id = "doc-" + re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:50]
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