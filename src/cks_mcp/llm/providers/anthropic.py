"""
Anthropic Messages API provider primitives.
"""

from __future__ import annotations

import json
import os
import time

from cks_mcp.llm.providers._shared import _record_llm_call
from cks_mcp.llm.redact import scrub_secrets
from cks_mcp.llm.retry import call_with_retry
from cks_mcp.observability.llm_telemetry import estimate_anthropic_cost

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

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Anthropic call ({model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
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

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Anthropic call ({resolved_model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
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
