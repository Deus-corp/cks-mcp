"""
construct_knowledge: build a Canonical Knowledge Structure from free-form text
using an LLM to extract entities, relations, and their structure.

The tool sends the user-supplied text to the configured LLM (Anthropic
claude-sonnet-4-6 by default), asks it to produce a valid CKS JSON payload,
then parses and validates that payload with cks-core before persisting it as
a new session.  Nothing is committed if the LLM output fails validation.

Environment variables:
    ANTHROPIC_API_KEY   — required; Anthropic API key.
    CKS_LLM_MODEL       — optional override (default: claude-sonnet-4-6).
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
    model = arguments.get("model") or os.environ.get(
        "CKS_LLM_MODEL", "claude-sonnet-4-6"
    )
    max_tokens = int(
        arguments.get("max_tokens")
        or os.environ.get("CKS_LLM_MAX_TOKENS", "4096")
    )

    # Build the user prompt
    user_prompt_parts = [f"Extract a Canonical Knowledge Structure from the following text:\n\n{text}"]
    if hint:
        user_prompt_parts.append(f"\nFocus especially on: {hint}")
    user_prompt = "\n".join(user_prompt_parts)

    # 1. Call LLM
    try:
        raw_output = _call_anthropic(user_prompt, model=model, max_tokens=max_tokens)
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