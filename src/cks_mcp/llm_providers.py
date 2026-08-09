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
import logging
import os
import time

from cks_mcp.llm_telemetry import (
    estimate_anthropic_cost,
    estimate_tokens_from_chars,
    llm_telemetry,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ollama (local, no API key)
# ---------------------------------------------------------------------------


def ollama_host() -> str:
    return os.environ.get("CKS_OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _record_llm_call(
    *,
    provider: str,
    model: str,
    tool: str,
    tokens: int,
    start: float,
    success: bool,
    error_type: str | None = None,
    cost_estimate: float = 0.0,
) -> None:
    """Shared record_call plumbing for call_ollama/call_anthropic: turns a
    monotonic `start` timestamp into a duration_ms and forwards to the
    llm_telemetry singleton. Never raises -- telemetry must never break
    the actual LLM call it's observing."""
    try:
        llm_telemetry.record_call(
            provider,
            model,
            tool,
            tokens,
            (time.monotonic() - start) * 1000,
            success,
            error_type=error_type,
            cost_estimate=cost_estimate,
        )
    except Exception as exc:  # noqa: BLE001 -- telemetry is best-effort, never fatal
        _logger.debug("llm_telemetry.record_call failed: %s", exc)


def ollama_available(host: str | None = None) -> bool:
    """Cheap reachability check used by 'auto' provider selection. Never raises."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{host or ollama_host()}/api/tags", timeout=1.5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def call_ollama(
    prompt: str,
    *,
    system_prompt: str,
    model: str,
    max_tokens: int,
    tool_name: str | None = None,
) -> str:
    """
    Call a local Ollama server's generate endpoint. Raises RuntimeError with
    a descriptive message (including how to fix it) on any failure.

    If ``tool_name`` is given, records the call in ``llm_telemetry`` --
    tokens are estimated from character length (chars / 4) since Ollama's
    ``/api/generate`` response carries no ``usage`` field; cost is always
    0.0 (a local model has no per-token API billing).
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
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(system_prompt + prompt),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Ollama returned HTTP {exc.code}: {raw[:400]}. "
            f"Is model '{model}' pulled? Try: ollama pull {model}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(system_prompt + prompt),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Could not reach Ollama at {host}: {exc.reason}. "
            "Is `ollama serve` running? Install: https://ollama.com"
        ) from exc

    text = body.get("response", "")
    if not text:
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(system_prompt + prompt),
                start=start,
                success=False,
                error_type="EmptyResponse",
            )
        raise RuntimeError(f"Ollama returned no text. Full response: {body}")

    if tool_name is not None:
        _record_llm_call(
            provider="ollama",
            model=model,
            tool=tool_name,
            tokens=estimate_tokens_from_chars(system_prompt + prompt + text),
            start=start,
            success=True,
        )
    return text


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------


def call_anthropic(
    prompt: str,
    *,
    system_prompt: str,
    model: str,
    max_tokens: int,
    tool_name: str | None = None,
) -> str:
    """
    Call the Anthropic Messages API synchronously via stdlib urllib.

    Returns the text content of the first content block. Raises
    ``RuntimeError`` with a descriptive message on any failure.

    If ``tool_name`` is given, records the call in ``llm_telemetry``:
    tokens and cost come from the API's own ``usage.input_tokens``/
    ``usage.output_tokens`` (real, billed figures) whenever the HTTP
    call succeeds -- even if the response then turns out to have no
    usable text block, since Anthropic still bills for that call --
    and are 0 only when the HTTP request itself never got a response
    (e.g. a network error, or a missing API key).
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

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Anthropic API returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(f"Network error calling Anthropic API: {exc.reason}") from exc

    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tokens = input_tokens + output_tokens
    cost_estimate = estimate_anthropic_cost(model, input_tokens, output_tokens)

    content = body.get("content", [])
    if not content:
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=model,
                tool=tool_name,
                tokens=tokens,
                start=start,
                success=False,
                error_type="NoContentBlocks",
                cost_estimate=cost_estimate,
            )
        raise RuntimeError(f"Anthropic API returned no content blocks: {body}")

    text_blocks = [b["text"] for b in content if b.get("type") == "text"]
    if not text_blocks:
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=model,
                tool=tool_name,
                tokens=tokens,
                start=start,
                success=False,
                error_type="NoTextBlocks",
                cost_estimate=cost_estimate,
            )
        raise RuntimeError(
            f"Anthropic API returned no text blocks. Stop reason: {body.get('stop_reason')}"
        )

    if tool_name is not None:
        _record_llm_call(
            provider="anthropic",
            model=model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
            cost_estimate=cost_estimate,
        )

    return "\n".join(text_blocks)


def call_anthropic_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    max_tokens: int = 4096,
    tool_name: str | None = None,
) -> dict:
    """POSTs to /v1/messages with 'tools' + 'tool_choice': 'auto'. Unlike
    call_anthropic (single-shot, text-in/text-out for construct_knowledge),
    this returns the raw response['content'] block list as-is (mixed
    text/tool_use blocks) -- ai_chat's loop needs the block structure, not
    a flattened string. Requires ANTHROPIC_API_KEY (see cks-mcp ADR-011
    §6); raises RuntimeError with a clear message if unset, same
    convention call_anthropic already uses for its own missing-key case.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "ai_chat requires an Anthropic API key (no Ollama tool-calling "
            "path yet -- see cks-mcp ADR-011 §6)."
        )

    resolved_model = model or os.environ.get(
        "CKS_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"
    )

    payload = json.dumps(
        {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "auto"},
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

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=resolved_model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Anthropic API returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="anthropic",
                model=resolved_model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(f"Network error calling Anthropic API: {exc.reason}") from exc

    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tokens = input_tokens + output_tokens
    cost_estimate = estimate_anthropic_cost(resolved_model, input_tokens, output_tokens)

    if tool_name is not None:
        _record_llm_call(
            provider="anthropic",
            model=resolved_model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
            cost_estimate=cost_estimate,
        )

    return body


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------


def extract_json(raw: str) -> str:
    """
    Strip any accidental markdown fences the LLM may have emitted and
    return the first *balanced* JSON object found in *raw*, starting
    from the first ``{``.

    Brace-matching always runs -- even when ``raw`` already starts
    with ``{`` -- so that truncated output (e.g. cut off by
    ``max_tokens``) is reported as "unbalanced braces" instead of
    being passed through unchecked and failing later with a more
    confusing parse error, and so that trailing commentary after the
    JSON object (e.g. "Hope this helps!") is trimmed off rather than
    returned as part of the "extracted" JSON.
    """
    stripped = raw.strip()

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