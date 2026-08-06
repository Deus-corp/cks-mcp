"""
construct_knowledge: build a Canonical Knowledge Structure from free-form text
using an LLM to extract entities, relations, and their structure.

The tool sends the user-supplied text to a pluggable LLM provider, asks it to
produce a valid CKS JSON payload, then parses and validates that payload with
cks-core before persisting it as a new session. Nothing is committed if the
LLM output fails validation.

Provider selection (CKS_LLM_PROVIDER):
    "auto" (default) — use a local Ollama server if one is reachable at
                        CKS_OLLAMA_HOST (no API key needed); otherwise fall
                        back to Anthropic if ANTHROPIC_API_KEY is set.
    "ollama"          — force local Ollama. No API key required.
    "anthropic"       — force the Anthropic API. Requires ANTHROPIC_API_KEY.

If no provider is available, the tool returns an error explaining all three
options, including the option to skip this tool entirely: since the MCP
client calling this server is typically itself an LLM, it can build the CKS
JSON directly (the exact required shape is in _SYSTEM_PROMPT below) and pass
it straight to evolve_knowledge/validate_knowledge — no LLM call from the
server needed at all.

(MCP's "sampling" feature — letting the server ask the connected client's
model to do this — was deprecated in the 2026-07-28 protocol revision, so it
is intentionally not used here.)

Environment variables:
    CKS_LLM_PROVIDER    — "auto" (default) | "ollama" | "anthropic".
    ANTHROPIC_API_KEY   — required only for the "anthropic" provider.
    CKS_LLM_MODEL       — model override for the "anthropic" provider
                          (default: claude-sonnet-4-6).
    CKS_OLLAMA_MODEL    — model override for the "ollama" provider
                          (default: llama3.2).
    CKS_OLLAMA_HOST     — Ollama server URL (default: http://localhost:11434).
    CKS_LLM_MAX_TOKENS  — optional override (default: 4096).
"""

from __future__ import annotations

import os
from typing import Any

import cks
from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.errors import internal_error, missing_parameter

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a knowledge-extraction assistant. Given an input text, extract the key
entities and relationships and output them as a Canonical Knowledge Structure
(CKS) — a JSON object with a single top-level key "objects", whose value is an
array of object descriptors.

Every object descriptor must have:
  "identity": {"id": "<unique-slug>", "type": "<Type>", "name": "<human label>"}
  "structure": { ... free-form key-value metadata ... }

Relations are ordinary objects whose "structure" contains exactly:
  "participants": ["<id1>", "<id2>", ...] — at least two existing object ids
  "relation_type": "<verb>"              — e.g. "causes", "part_of", "derives"

Rules:
- Every id must be a unique kebab-case slug (e.g. "photosynthesis-concept").
- Every participant id in a relation must reference an object that exists in
  the same "objects" array.
- Do NOT invent ids that are not declared as objects.
- Output ONLY the raw JSON object — no markdown fences, no commentary.
- The structure must be valid CKS (parseable by cks.parse).

Example output:
{
  "objects": [
    {"identity": {"id": "obj-sun", "type": "Concept", "name": "Sun"},
     "structure": {"description": "The star at the centre of the Solar System"}},
    {"identity": {"id": "obj-earth", "type": "Concept", "name": "Earth"},
     "structure": {"description": "The third planet from the Sun"}},
    {"identity": {"id": "rel-orbits", "type": "Relation", "name": "Earth orbits Sun"},
     "structure": {"participants": ["obj-earth", "obj-sun"], "relation_type": "orbits"}}
  ]
}
"""

# ---------------------------------------------------------------------------
# LLM call -- thin wrappers around cks_mcp.llm_providers, binding in this
# tool's own _SYSTEM_PROMPT. Kept as module-level functions (rather than
# calling llm_providers directly from _call_llm/construct_knowledge) so
# existing tests can keep patching e.g.
# "cks_mcp.tools.construct_knowledge.handler._call_anthropic" -- the actual
# HTTP/urllib plumbing lives in llm_providers and is shared with
# ingest_document's optional LLM pass.
# ---------------------------------------------------------------------------


def _ollama_host() -> str:
    return llm_providers.ollama_host()


def _ollama_available(host: str | None = None) -> bool:
    return llm_providers.ollama_available(host)


def _call_ollama(prompt: str, model: str, max_tokens: int, tool_name: str) -> str:
    return llm_providers.call_ollama(
        prompt,
        system_prompt=_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name=tool_name,
    )


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


def _call_llm(
    prompt: str, *, model: str | None, max_tokens: int, tool_name: str = "construct_knowledge"
) -> tuple[str, str]:
    """
    Route the extraction prompt to whichever LLM provider is configured or
    available. Returns (raw_text, model_used). Raises RuntimeError with a
    message listing every option when no provider can be used.
    """
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, model=m, max_tokens=max_tokens, tool_name=tool_name), m

    if provider == "anthropic":
        m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
        return _call_anthropic(prompt, model=m, max_tokens=max_tokens, tool_name=tool_name), m

    if provider != "auto":
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', or 'anthropic'."
        )

    # auto: prefer a local, keyless model if one is already running; otherwise
    # fall through to Anthropic, which raises its own clear error if
    # ANTHROPIC_API_KEY isn't set either (caught below and rewrapped with the
    # full list of options).
    if _ollama_available():
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, model=m, max_tokens=max_tokens, tool_name=tool_name), m

    m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
    try:
        return _call_anthropic(prompt, model=m, max_tokens=max_tokens, tool_name=tool_name), m
    except RuntimeError as exc:
        if "ANTHROPIC_API_KEY" not in str(exc):
            raise
        raise RuntimeError(
            "No LLM provider available for construct_knowledge. Options: "
            "(1) run a local model — `ollama serve` + `ollama pull llama3.2` — "
            "no API key needed, this tool auto-detects it on localhost:11434; "
            "(2) set ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; "
            "(3) skip this tool: ask your LLM client to build the CKS JSON directly "
            "(same format as this tool's own system prompt) and pass it straight "
            "to evolve_knowledge or validate_knowledge — no server-side LLM call needed."
        ) from exc


def _call_anthropic(prompt: str, model: str, max_tokens: int, tool_name: str) -> str:
    return llm_providers.call_anthropic(
        prompt,
        system_prompt=_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name=tool_name,
    )


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> str:
    return llm_providers.extract_json(raw)


# ---------------------------------------------------------------------------
# Main tool handler
# ---------------------------------------------------------------------------


async def construct_knowledge(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    """
    MCP tool handler for construct_knowledge.

    Accepts free-form ``text`` (required), an optional ``hint`` describing
    what aspects to focus on, and optional LLM overrides (``model``,
    ``max_tokens``).  On success creates a new session and returns the
    serialized structure together with ``session_id`` and ``version_id``.
    """
    text = arguments.get("text", "").strip()
    if not text:
        return missing_parameter("text")

    hint = arguments.get("hint", "").strip()
    model = arguments.get("model") or None
    max_tokens = int(
        arguments.get("max_tokens")
        or os.environ.get("CKS_LLM_MAX_TOKENS", "4096")
    )
    # Internal-only override: other tools that build knowledge by calling
    # this handler as a plain Python function (update_registered_graph)
    # pass their own name here so LLM telemetry attributes the call to the
    # tool a human actually invoked, not construct_knowledge itself. Never
    # part of the public schema -- absent (defaulting to "construct_knowledge")
    # for every call that comes in through the registered MCP tool.
    tool_name = arguments.get("_tool_name") or "construct_knowledge"

    # Build the user prompt
    user_prompt_parts = [f"Extract a Canonical Knowledge Structure from the following text:\n\n{text}"]
    if hint:
        user_prompt_parts.append(f"\nFocus especially on: {hint}")
    user_prompt = "\n".join(user_prompt_parts)

    # 1. Call LLM (provider auto-selected or forced via CKS_LLM_PROVIDER)
    try:
        raw_output, model = _call_llm(
            user_prompt, model=model, max_tokens=max_tokens, tool_name=tool_name
        )
    except RuntimeError as exc:
        return internal_error(f"LLM call failed: {exc}")

    # 2. Extract JSON
    try:
        json_str = _extract_json(raw_output)
    except ValueError as exc:
        return {
            "error": "llm_output_parse_error",
            "message": str(exc),
            "raw_output": raw_output[:1000],
        }

    # 3. Parse with cks-core
    try:
        structure = cks.parse(json_str)
    except cks.SerializationError as exc:
        return {
            "error": "cks_parse_error",
            "message": str(exc),
            "raw_json": json_str[:2000],
        }

    # 4. Validate
    validation = cks.validate(structure)
    if not validation.is_valid:
        return {
            "error": "validation_failed",
            "message": "LLM-generated structure failed CKS validation.",
            "raw_json": json_str[:2000],
            "diagnostics": [
                {
                    "code": d.identity,
                    "severity": d.severity.value,
                    "message": d.message,
                    "location": d.location,
                }
                for d in validation.diagnostics
            ],
        }

    # 5. Persist as a new session
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    version = await runtime.commit_transaction(tx)

    from cks.core import CanonicalRelation

    serialized = runtime.core_bridge.serialize(session.knowledge_structure)
    return {
        "constructed": True,
        "session_id": session.session_id,
        "version_id": version.version_id,
        "serialized": serialized,
        "objects_count": sum(
            1
            for obj in structure.objects
            if not isinstance(obj, CanonicalRelation)
        ),
        "relations_count": len(structure.relations()),
        "model_used": model,
    }