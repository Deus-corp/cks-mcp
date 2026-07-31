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

import json
import os
from typing import Any

import cks
from cks_runtime.runtime import Runtime

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
# LLM call (httpx-free: uses stdlib urllib so no extra dependency)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Local LLM call via Ollama (no dependency, no API key — plain stdlib urllib
# against Ollama's own local HTTP API)
# ---------------------------------------------------------------------------


def _ollama_host() -> str:
    return os.environ.get("CKS_OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _ollama_available(host: str | None = None) -> bool:
    """Cheap reachability check used by the 'auto' provider. Never raises."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{host or _ollama_host()}/api/tags", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _call_ollama(prompt: str, model: str, max_tokens: int) -> str:
    """
    Call a local Ollama server's generate endpoint. Raises RuntimeError with
    a descriptive message (including how to fix it) on any failure.
    """
    import urllib.error
    import urllib.request

    host = _ollama_host()
    payload = json.dumps(
        {
            "model": model,
            "system": _SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
    ).encode()

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"Ollama returned HTTP {exc.code}: {raw[:400]}. "
            f"Is model '{model}' pulled? Try: ollama pull {model}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {host}: {exc.reason}. "
            "Is `ollama serve` running? Install: https://ollama.com"
        ) from exc

    text = body.get("response", "")
    if not text:
        raise RuntimeError(f"Ollama returned no text. Full response: {body}")
    return text


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> tuple[str, str]:
    """
    Route the extraction prompt to whichever LLM provider is configured or
    available. Returns (raw_text, model_used). Raises RuntimeError with a
    message listing every option when no provider can be used.
    """
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, model=m, max_tokens=max_tokens), m

    if provider == "anthropic":
        m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
        return _call_anthropic(prompt, model=m, max_tokens=max_tokens), m

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
        return _call_ollama(prompt, model=m, max_tokens=max_tokens), m

    m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
    try:
        return _call_anthropic(prompt, model=m, max_tokens=max_tokens), m
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


def _call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
    """
    Call the Anthropic Messages API synchronously via stdlib urllib.

    Returns the text content of the first content block.  Raises
    ``RuntimeError`` with a descriptive message on any failure.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "construct_knowledge requires an Anthropic API key."
        )

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"Anthropic API returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error calling Anthropic API: {exc.reason}") from exc

    content = body.get("content", [])
    if not content:
        raise RuntimeError(f"Anthropic API returned no content blocks: {body}")

    text_blocks = [b["text"] for b in content if b.get("type") == "text"]
    if not text_blocks:
        raise RuntimeError(
            f"Anthropic API returned no text blocks. Stop reason: {body.get('stop_reason')}"
        )

    return "\n".join(text_blocks)


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> str:
    """
    Strip any accidental markdown fences the LLM may have emitted and
    return the first JSON object found in *raw*.

    Order of preference:
    1. The raw string itself — if it starts with ``{`` after stripping.
    2. Content between the first ``{`` and its matching ``}``.
    """
    stripped = raw.strip()
    if stripped.startswith("{"):
        return stripped

    # Find balanced braces
    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM output.")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]

    raise ValueError("Unbalanced braces in LLM output — could not extract JSON.")


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

    # Build the user prompt
    user_prompt_parts = [f"Extract a Canonical Knowledge Structure from the following text:\n\n{text}"]
    if hint:
        user_prompt_parts.append(f"\nFocus especially on: {hint}")
    user_prompt = "\n".join(user_prompt_parts)

    # 1. Call LLM (provider auto-selected or forced via CKS_LLM_PROVIDER)
    try:
        raw_output, model = _call_llm(user_prompt, model=model, max_tokens=max_tokens)
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