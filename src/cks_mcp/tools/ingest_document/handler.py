"""
ingest_document: fetch a URL, extract structured content (JSON-LD,
OpenGraph, microdata, tables, lists, sections) and optionally use an LLM
to build a full Canonical Knowledge Structure from the extracted data.

Uses the same SSRF/DNS-rebinding protection as verify_source.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import json
import os
import re
from collections import Counter
from typing import Any

import cks
from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.errors import internal_error
from cks_mcp.tools.ingest_document.html_extract import parse_document_structure
from cks_mcp.tools.verify_source.handler import UnsafeURLError, _safe_request

# ---------------------------------------------------------------------------
# HTML → text (kept for keyword extraction)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]*>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")
_WHITESPACE_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _ENTITY_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Entity extraction (keywords)
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
    words = re.findall(rf"\b[a-zA-Z]{{{_MIN_KEYWORD_LENGTH},}}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counter = Counter(filtered)
    return [word for word, _ in heapq.nlargest(max_keywords, counter.items(), key=lambda x: x[1])]


# ---------------------------------------------------------------------------
# LLM system prompt (used when use_llm=True)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_INGEST = """\
You are a knowledge-extraction assistant. You are given structured content
extracted from a web page: a title, description, metadata (JSON-LD, OpenGraph,
etc.), headings with their sections, tables, and lists.

From this content, extract the key entities and relationships and output them as a
Canonical Knowledge Structure (CKS) — a JSON object with a single top-level key
"objects", whose value is an array of object descriptors.

Every object descriptor must have:
  "identity": {"id": "<unique-slug>", "type": "<Type>", "name": "<human label>"}
  "structure": { ... free-form key-value metadata ... }

Relations are ordinary objects whose "structure" contains exactly:
  "participants": ["<id1>", "<id2>", ...] — at least two existing object ids
  "relation_type": "<verb>"              — e.g. "causes", "part_of", "derives"

Rules:
- Every id must be a unique kebab-case slug.
- Every participant id in a relation must reference an object that exists in
  the same "objects" array.
- Do NOT invent ids that are not declared as objects.
- Output ONLY the raw JSON object — no markdown fences, no commentary.
- The structure must be valid CKS (parseable by cks.parse).

Example:
{
  "objects": [
    {"identity": {"id": "doc-example", "type": "Document", "name": "Example Page"},
     "structure": {"url": "https://example.com", "title": "Example"}},
    {"identity": {"id": "concept-photosynthesis", "type": "Concept", "name": "Photosynthesis"},
     "structure": {"description": "Process by which plants convert light to energy"}},
    {"identity": {"id": "rel-mentions", "type": "Relation", "name": "mentions"},
     "structure": {"participants": ["doc-example", "concept-photosynthesis"], "relation_type": "mentions"}}
  ]
}
"""


def _build_llm_structure(
    extracted: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[cks.KnowledgeStructure, str | None]:
    """Send extracted content to LLM and return the parsed CKS structure and model name."""
    # Build prompt from extracted structured data
    prompt_parts = ["Build a Knowledge Structure from the following extracted web page content:\n"]
    if extracted.get("title"):
        prompt_parts.append(f"Title: {extracted['title']}")
    if extracted.get("description"):
        prompt_parts.append(f"Description: {extracted['description']}")
    if extracted.get("sections"):
        prompt_parts.append("Sections:")
        for sec in extracted["sections"]:
            prompt_parts.append(f"  - Heading: {sec.get('heading') or '(none)'} (level {sec['level']})\n    Content: {sec['content']}")
    if extracted.get("tables"):
        prompt_parts.append("Tables:")
        for i, tbl in enumerate(extracted["tables"]):
            prompt_parts.append(f"  Table {i+1}: caption={tbl.get('caption')}, headers={tbl.get('headers')}, rows={tbl['rows']}")
    if extracted.get("lists"):
        prompt_parts.append("Lists:")
        for i, lst in enumerate(extracted["lists"]):
            ordered = "ordered" if lst.get("ordered") else "unordered"
            prompt_parts.append(f"  List {i+1} ({ordered}): {lst['items']}")
    if extracted.get("metadata"):
        prompt_parts.append("Metadata (JSON-LD, OpenGraph, etc.):")
        prompt_parts.append(json.dumps(extracted["metadata"], indent=2))

    user_prompt = "\n".join(prompt_parts)

    model = arguments.get("model") or None
    max_tokens = int(
        arguments.get("max_tokens") or os.environ.get("CKS_LLM_MAX_TOKENS", "4096")
    )
    # Internal-only override, same convention as construct_knowledge's
    # "_tool_name": the Enrichment Agent calls this handler as a plain
    # Python function and passes its own name here so LLM telemetry
    # attributes the call to the agent, not to ingest_document itself.
    # Never part of the public schema.
    tool_name = arguments.get("_tool_name") or "ingest_document"

    # Provider dispatch: mirrors construct_knowledge.handler._call_llm, but
    # bound to our own system prompt. Only the low-level HTTP primitives
    # (call_ollama/call_anthropic/call_openai_compatible_single_shot/
    # call_google/ollama_available) are shared via llm_providers -- this
    # branching is a separate copy. See test_llm_dispatch.py for coverage
    # of these branches; keep both copies in sync if the fallback logic
    # changes. 'auto' never picks 'openai_compatible' or 'google' -- same
    # convention as every other provider router in cks-mcp -- they must be
    # selected explicitly via CKS_LLM_PROVIDER.
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    def call_ollama(prompt: str, model: str, max_tokens: int) -> str:
        return llm_providers.call_ollama(
            prompt,
            system_prompt=_SYSTEM_PROMPT_INGEST,
            model=model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )

    def call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
        return llm_providers.call_anthropic(
            prompt,
            system_prompt=_SYSTEM_PROMPT_INGEST,
            model=model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )

    def call_openai_compatible(prompt: str, model: str, max_tokens: int) -> str:
        return llm_providers.call_openai_compatible_single_shot(
            prompt,
            system_prompt=_SYSTEM_PROMPT_INGEST,
            model=model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )

    def call_google(prompt: str, model: str, max_tokens: int) -> str:
        return llm_providers.call_google(
            prompt,
            system_prompt=_SYSTEM_PROMPT_INGEST,
            model=model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        raw_output = call_ollama(user_prompt, model=m, max_tokens=max_tokens)
        model_used = m
    elif provider == "anthropic":
        m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
        raw_output = call_anthropic(user_prompt, model=m, max_tokens=max_tokens)
        model_used = m
    elif provider == "openai_compatible":
        m = model or os.environ.get("CKS_OPENAI_MODEL", "gpt-4o")
        raw_output = call_openai_compatible(user_prompt, model=m, max_tokens=max_tokens)
        model_used = m
    elif provider == "google":
        m = model or os.environ.get("CKS_GOOGLE_MODEL", "gemini-2.5-flash")
        raw_output = call_google(user_prompt, model=m, max_tokens=max_tokens)
        model_used = m
    elif provider == "auto":
        if llm_providers.ollama_available():
            m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
            raw_output = call_ollama(user_prompt, model=m, max_tokens=max_tokens)
            model_used = m
        else:
            m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
            try:
                raw_output = call_anthropic(user_prompt, model=m, max_tokens=max_tokens)
                model_used = m
            except RuntimeError as exc:
                if "ANTHROPIC_API_KEY" not in str(exc):
                    raise
                raise RuntimeError(
                    "No LLM provider available. Options: "
                    "(1) run a local model — `ollama serve` + `ollama pull llama3.2`; "
                    "(2) set ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; "
                    "(3) set CKS_OPENAI_API_KEY and CKS_LLM_PROVIDER=openai_compatible "
                    "to use OpenAI or any OpenAI-compatible endpoint; "
                    "(4) set CKS_GOOGLE_API_KEY and CKS_LLM_PROVIDER=google to use "
                    "Google Gemini; "
                    "(5) retry without use_llm to get a baseline structure."
                ) from exc
    else:
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', 'anthropic', "
            "'google', or 'openai_compatible'."
        )

    # Extract JSON from LLM output
    try:
        json_str = llm_providers.extract_json(raw_output)
    except ValueError as exc:
        raise RuntimeError(f"Failed to extract JSON from LLM output: {exc}") from exc

    # Parse with cks-core
    try:
        structure = cks.parse(json_str)
    except cks.SerializationError as exc:
        raise RuntimeError(f"LLM output is not valid CKS: {exc}") from exc

    # Validate (optional but recommended)
    validation = cks.validate(structure)
    if not validation.is_valid:
        # We still return it, but caller may decide to fall back
        pass  # structure is still usable

    return structure, model_used


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def ingest_document(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch a URL, extract structured content (sections, tables, lists, metadata)
    and build a Canonical Knowledge Structure.

    If ``use_llm`` is ``true``, the extracted content is sent to an LLM (same
    provider auto-selection as ``construct_knowledge``) to build a richer graph.
    Otherwise, a deterministic structure with Document, Section, Table, List,
    Metadata and Topic objects is returned.
    """
    url = arguments.get("url")
    if not url:
        return {"error": "missing_parameter", "message": "Missing required parameter: 'url'."}

    use_llm = arguments.get("use_llm", False)

    # ---- Fetch the page, safely ---------------------------------------------
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

    # ---- Extract metadata and plain text -----------------------------------
    title, description = _extract_title_and_description(html)
    plain_text = _html_to_text(html[:200_000])
    keywords = _extract_keywords(plain_text)

    # ---- Structured extraction (NEW) ---------------------------------------
    parser = parse_document_structure(html)
    extracted: dict[str, Any] = {
        "title": title,
        "description": description,
        "metadata": {
            "json_ld": parser.json_ld,
            "open_graph": parser.open_graph,
            "twitter": parser.twitter,
            "meta": parser.meta,
        },
        "tables": parser.tables,
        "lists": parser.lists,
        "sections": parser.sections,
    }

    # ---- Build Knowledge Structure -----------------------------------------
    _url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    _safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:30]
    doc_id = f"doc-{_safe_prefix}-{_url_hash}"
    objects = []
    relations = []

    # If use_llm, delegate everything to the LLM
    if use_llm:
        try:
            llm_structure, model_used = _build_llm_structure(extracted, arguments)
        except RuntimeError as exc:
            return internal_error(f"LLM call failed: {exc}")

        # Serialize for response
        serialized = runtime.core_bridge.serialize(llm_structure)
        return {
            "url": url,
            "title": title,
            "keywords": keywords,
            "knowledge_structure": serialized,
            "object_count": sum(
                1 for obj in llm_structure.objects
                if not isinstance(obj, cks.CanonicalRelation)
            ),
            "relation_count": len(llm_structure.relations()),
            "model_used": model_used,
        }

    # ---- Deterministic structure --------------------------------------------
    # Document object (as before)
    doc_structure = {"url": url, "content_preview": plain_text[:500]}
    if title:
        doc_structure["title"] = title
    if description:
        doc_structure["description"] = description
    objects.append({
        "identity": {"id": doc_id, "type": "Document", "name": title or url},
        "structure": doc_structure,
    })

    # Keyword objects + relations (keep for backward compatibility)
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

    # Metadata object
    meta_obj_id = f"{doc_id}-metadata"
    objects.append({
        "identity": {"id": meta_obj_id, "type": "Metadata", "name": f"Metadata for {title or url}"},
        "structure": extracted["metadata"],
    })
    relations.append({
        "identity": {"id": f"rel-{meta_obj_id}", "type": "Relation", "name": "has_metadata"},
        "structure": {
            "participants": [doc_id, meta_obj_id],
            "relation_type": "has_metadata",
        },
    })

    # Section objects
    for i, section in enumerate(parser.sections):
        sec_id = f"{doc_id}-section-{i}"
        objects.append({
            "identity": {"id": sec_id, "type": "Section", "name": section.get("heading") or f"Section {i+1}"},
            "structure": {
                "heading": section["heading"],
                "level": section["level"],
                "content": section["content"],
            },
        })
        relations.append({
            "identity": {"id": f"rel-{sec_id}", "type": "Relation", "name": "has_section"},
            "structure": {
                "participants": [doc_id, sec_id],
                "relation_type": "has_section",
            },
        })

    # Table objects
    for i, table in enumerate(parser.tables):
        tbl_id = f"{doc_id}-table-{i}"
        objects.append({
            "identity": {"id": tbl_id, "type": "Table", "name": table.get("caption") or f"Table {i+1}"},
            "structure": table,
        })
        relations.append({
            "identity": {"id": f"rel-{tbl_id}", "type": "Relation", "name": "has_table"},
            "structure": {
                "participants": [doc_id, tbl_id],
                "relation_type": "has_table",
            },
        })

    # List objects
    for i, lst in enumerate(parser.lists):
        lst_id = f"{doc_id}-list-{i}"
        objects.append({
            "identity": {"id": lst_id, "type": "List", "name": f"List {i+1}"},
            "structure": lst,
        })
        relations.append({
            "identity": {"id": f"rel-{lst_id}", "type": "Relation", "name": "has_list"},
            "structure": {
                "participants": [doc_id, lst_id],
                "relation_type": "has_list",
            },
        })

    # Build combined structure
    all_objects = objects + relations
    structure_json = json.dumps({"objects": all_objects})
    try:
        structure = cks.parse(structure_json)
    except cks.SerializationError as exc:
        return internal_error(f"Failed to build Knowledge Structure: {exc}")

    serialized = runtime.core_bridge.serialize(structure)
    return {
        "url": url,
        "title": title,
        "keywords": keywords,
        "knowledge_structure": serialized,
        "object_count": len(structure.objects),
        "relation_count": len(structure.relations()),
    }