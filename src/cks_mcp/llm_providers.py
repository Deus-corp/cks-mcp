"""
Shared, low-level LLM provider primitives (Ollama + Anthropic).

This module has no opinion about *what* system prompt to send or how
to interpret the result -- that stays with whichever tool imports
these primitives (``construct_knowledge``, ``ingest_document``, ...)
and layers its own prompt/parsing/merge logic on top. Factoring the
provider plumbing out here means the fiddly bits -- reachability
probing, urllib error handling, JSON-from-markdown extraction -- are
implemented once and shared, instead of drifting between copies as
each tool evolves independently.

Environment variables (read by callers, not by this module, except
``CKS_OLLAMA_HOST``):
    CKS_OLLAMA_HOST   -- Ollama server URL (default: http://localhost:11434).
"""

from __future__ import annotations

import json
import os

# ---------------------------------------------------------------------------
# Ollama (local, no API key)
# ---------------------------------------------------------------------------


def ollama_host() -> str:
    return os.environ.get("CKS_OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def ollama_available(host: str | None = None) -> bool:
    """Cheap reachability check used by 'auto' provider selection. Never raises."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{host or ollama_host()}/api/tags", timeout=1.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def call_ollama(prompt: str, *, system_prompt: str, model: str, max_tokens: int) -> str:
    """
    Call a local Ollama server's generate endpoint. Raises RuntimeError with
    a descriptive message (including how to fix it) on any failure.
    """
    import urllib.error
    import urllib.request

    host = ollama_host()
    payload = json.dumps(
        {
            "model": model,
            "system": system_prompt,
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
# Anthropic API
# ---------------------------------------------------------------------------


def call_anthropic(prompt: str, *, system_prompt: str, model: str, max_tokens: int) -> str:
    """
    Call the Anthropic Messages API synchronously via stdlib urllib.

    Returns the text content of the first content block. Raises
    ``RuntimeError`` with a descriptive message on any failure.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "This tool requires an Anthropic API key to use the 'anthropic' provider."
        )

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
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


def extract_json(raw: str) -> str:
    """
    Strip any accidental markdown fences the LLM may have emitted and
    return the first JSON object found in *raw*.

    Order of preference:
    1. The raw string itself -- if it starts with ``{`` after stripping.
    2. Content between the first ``{`` and its matching ``}``.
    """
    stripped = raw.strip()
    if stripped.startswith("{"):
        return stripped

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

    raise ValueError("Unbalanced braces in LLM output -- could not extract JSON.")