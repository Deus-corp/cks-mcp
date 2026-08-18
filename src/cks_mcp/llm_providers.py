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
from typing import Any

from cks_mcp.llm.redact import scrub_secrets
from cks_mcp.llm.retry import call_with_retry
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
    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Ollama call ({model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
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


# ---------------------------------------------------------------------------
# Ollama tool-calling (/api/chat) -- used by ai_chat (cks-mcp ADR-011 §6)
# ---------------------------------------------------------------------------
#
# call_ollama/call_anthropic above are single-shot text-in/text-out.
# ai_chat needs *tool calling*: the LLM must be able to request one or
# more tool invocations and receive their results back in a follow-up
# turn. Anthropic's native shape for that is a list of content blocks
# ({'type': 'text', ...} / {'type': 'tool_use', ...}); the functions
# below translate to/from Ollama's /api/chat shape so
# call_ollama_with_tools can return the *same* {'content': [...]}
# envelope call_anthropic_with_tools does, keeping ai_chat's loop
# provider-agnostic.


def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped messages (content: str | block[]) into
    Ollama /api/chat messages (content: str, optional tool_calls[])."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in content or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": block.get("input") or {},
                        }
                    }
                )
            elif btype == "tool_result":
                # Ollama has no 'tool_result' content block -- it uses a
                # dedicated 'tool' message role instead, one per result.
                result_content = block.get("content", "")
                if not isinstance(result_content, str):
                    result_content = json.dumps(result_content, ensure_ascii=False)
                out.append({"role": "tool", "content": result_content})

        if text_parts or tool_calls:
            msg: dict = {"role": role, "content": "".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)

    return out


def _to_ollama_tools(tools: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped tool specs ({'name', 'description',
    'input_schema'}) into Ollama's function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _from_ollama_chat_response(body: dict) -> dict:
    """Translate an Ollama /api/chat response into the same
    {'content': [block, ...]} envelope call_anthropic_with_tools
    returns, so ai_chat's loop doesn't need to know which provider
    answered."""
    message = body.get("message") or {}
    content: list[dict] = []

    text = message.get("content") or ""
    if text:
        content.append({"type": "text", "text": text})

    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                args = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"ollama_tool_{i}",
                "name": fn.get("name", ""),
                "input": args or {},
            }
        )

    if not content:
        # Keep the envelope well-formed (ai_chat treats an empty text
        # block as "no tool calls, empty final reply") rather than
        # leaving 'content' empty, which would look like a malformed
        # Anthropic response to the rest of the loop.
        content.append({"type": "text", "text": ""})

    return {"content": content}


def call_ollama_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    max_tokens: int = 4096,
    tool_name: str | None = None,
) -> dict:
    """POSTs to Ollama's ``/api/chat`` with ``tools``, mirroring
    ``call_anthropic_with_tools``'s contract: returns
    ``{'content': [block, ...]}`` using the same block shapes
    (``{'type': 'text', ...}`` / ``{'type': 'tool_use', ...}``) so
    ai_chat's loop is provider-agnostic (see cks-mcp ADR-011 §6).
    Raises ``RuntimeError`` with a descriptive, actionable message on
    any failure -- same convention as ``call_ollama`` /
    ``call_anthropic_with_tools``. Requires a model that supports
    Ollama tool calling (e.g. llama3.1+, qwen2.5); models that don't
    will simply never emit ``tool_calls`` and ai_chat will treat every
    turn as a final text reply.
    """
    import urllib.error
    import urllib.request

    host = ollama_host()
    resolved_model = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")

    ollama_messages = _to_ollama_messages(messages)
    payload = json.dumps(
        {
            "model": resolved_model,
            "messages": ollama_messages,
            "tools": _to_ollama_tools(tools),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
    ).encode()

    req = urllib.request.Request(
        f"{host}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    approx_input_text = json.dumps(ollama_messages)

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Ollama call ({resolved_model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Ollama returned HTTP {exc.code}: {raw[:400]}. "
            f"Is model '{resolved_model}' pulled? Try: ollama pull {resolved_model}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Could not reach Ollama at {host}: {exc.reason}. "
            "Is `ollama serve` running? Install: https://ollama.com"
        ) from exc

    if "message" not in body:
        if tool_name is not None:
            _record_llm_call(
                provider="ollama",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type="NoMessage",
            )
        raise RuntimeError(f"Ollama returned no 'message' field. Full response: {body}")

    result = _from_ollama_chat_response(body)

    if tool_name is not None:
        output_text = "".join(
            b.get("text", "") for b in result["content"] if b.get("type") == "text"
        )
        _record_llm_call(
            provider="ollama",
            model=resolved_model,
            tool=tool_name,
            tokens=estimate_tokens_from_chars(approx_input_text + output_text),
            start=start,
            success=True,
        )

    return result


# ---------------------------------------------------------------------------
# OpenAI-compatible tool-calling (/chat/completions) -- used by ai_chat
# ---------------------------------------------------------------------------
#
# Works with any provider that implements the OpenAI Chat Completions
# API shape (OpenAI, Groq, DeepSeek, Together, LM Studio, vLLM, ...).
# Translates to/from that shape so call_openai_compatible_with_tools
# returns the same {'content': [...]} envelope as
# call_anthropic_with_tools / call_ollama_with_tools, keeping ai_chat's
# loop provider-agnostic.


def openai_base_url() -> str:
    return os.environ.get("CKS_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped tool specs ({'name', 'description',
    'input_schema'}) into OpenAI's function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped messages (content: str | block[]) into
    OpenAI /chat/completions messages (content: str, optional
    tool_calls[], plus one 'tool' role message per tool_result block)."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in content or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
            elif btype == "tool_result":
                # OpenAI has no 'tool_result' content block -- it uses a
                # dedicated 'tool' message role instead, one per result,
                # referencing the originating tool_call_id.
                result_content = block.get("content", "")
                if not isinstance(result_content, str):
                    result_content = json.dumps(result_content, ensure_ascii=False)
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": result_content,
                    }
                )

        if text_parts or tool_calls:
            msg: dict = {"role": role, "content": "".join(text_parts)}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)

    return out


def _from_openai_chat_response(body: dict) -> dict:
    """Translate an OpenAI /chat/completions response into the same
    {'content': [block, ...]} envelope call_anthropic_with_tools
    returns, so ai_chat's loop doesn't need to know which provider
    answered."""
    choices = body.get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    content: list[dict] = []

    text = message.get("content") or ""
    if text:
        content.append({"type": "text", "text": text})

    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                args = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"openai_tool_{i}",
                "name": fn.get("name", ""),
                "input": args or {},
            }
        )

    if not content:
        # Keep the envelope well-formed (ai_chat treats an empty text
        # block as "no tool calls, empty final reply") rather than
        # leaving 'content' empty, which would look like a malformed
        # Anthropic response to the rest of the loop.
        content.append({"type": "text", "text": ""})

    return {"content": content}


def call_openai_compatible_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    max_tokens: int = 4096,
    tool_name: str | None = None,
) -> dict:
    """POSTs to ``{CKS_OPENAI_BASE_URL}/chat/completions`` with 'tools'
    + 'tool_choice': 'auto', mirroring ``call_anthropic_with_tools``'s
    contract: returns ``{'content': [block, ...]}`` using the same
    block shapes (``{'type': 'text', ...}`` / ``{'type': 'tool_use',
    ...}``) so ai_chat's loop is provider-agnostic. Works with any
    OpenAI-compatible endpoint -- OpenAI, Groq, DeepSeek, Together, LM
    Studio, vLLM, etc -- by pointing CKS_OPENAI_BASE_URL at it. Raises
    RuntimeError with a descriptive, actionable message on any
    failure -- same convention as ``call_anthropic_with_tools`` /
    ``call_ollama_with_tools``.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("CKS_OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "CKS_OPENAI_API_KEY environment variable is not set. "
            "This tool requires an API key to use the 'openai_compatible' provider "
            "(set it to any value your endpoint accepts, e.g. a local LM Studio "
            "instance may accept a dummy key)."
        )

    base_url = openai_base_url()
    resolved_model = model or os.environ.get("CKS_OPENAI_MODEL", "gpt-4o")

    openai_messages = _to_openai_messages(messages)
    payload = json.dumps(
        {
            "model": resolved_model,
            "messages": openai_messages,
            "tools": _to_openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "stream": False,
        }
    ).encode()

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    approx_input_text = json.dumps(openai_messages)

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"OpenAI-compatible call ({resolved_model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"OpenAI-compatible API at {base_url} returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Network error calling OpenAI-compatible API at {base_url}: {exc.reason}"
        ) from exc

    if "choices" not in body or not body["choices"]:
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type="NoChoices",
            )
        raise RuntimeError(
            f"OpenAI-compatible API at {base_url} returned no 'choices'. Full response: {body}"
        )

    result = _from_openai_chat_response(body)

    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    if not tokens:
        output_text = "".join(
            b.get("text", "") for b in result["content"] if b.get("type") == "text"
        )
        tokens = estimate_tokens_from_chars(approx_input_text + output_text)

    if tool_name is not None:
        _record_llm_call(
            provider="openai_compatible",
            model=resolved_model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
        )

    return result


def call_openai_compatible_single_shot(
    prompt: str,
    *,
    system_prompt: str,
    model: str,
    max_tokens: int,
    tool_name: str | None = None,
) -> str:
    """
    Call an OpenAI-compatible ``/chat/completions`` endpoint synchronously,
    single-shot text-in/text-out (no tools) -- the same contract
    ``call_ollama``/``call_anthropic`` already provide for
    ``construct_knowledge`` and ``ingest_document``'s ``use_llm`` mode.

    Works with any provider that implements the OpenAI Chat Completions
    API shape (OpenAI, Groq, DeepSeek, Together, LM Studio, vLLM, ...) by
    pointing ``CKS_OPENAI_BASE_URL`` at it. Raises ``RuntimeError`` with a
    descriptive message on any failure, same convention as
    ``call_anthropic``.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("CKS_OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "CKS_OPENAI_API_KEY environment variable is not set. "
            "This tool requires an API key to use the 'openai_compatible' provider "
            "(set it to any value your endpoint accepts, e.g. a local LM Studio "
            "instance may accept a dummy key)."
        )

    base_url = openai_base_url()

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    ).encode()

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"OpenAI-compatible call ({model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"OpenAI-compatible API at {base_url} returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Network error calling OpenAI-compatible API at {base_url}: {exc.reason}"
        ) from exc

    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)

    choices = body.get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    text = message.get("content") or ""

    if not tokens:
        tokens = estimate_tokens_from_chars(system_prompt + prompt + text)

    if not text:
        if tool_name is not None:
            _record_llm_call(
                provider="openai_compatible",
                model=model,
                tool=tool_name,
                tokens=tokens,
                start=start,
                success=False,
                error_type="EmptyResponse",
            )
        raise RuntimeError(f"OpenAI-compatible API returned no text. Full response: {body}")

    if tool_name is not None:
        _record_llm_call(
            provider="openai_compatible",
            model=model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
        )

    return text


# ---------------------------------------------------------------------------
# Google Gemini (native -- required for correct tool-calling with
# thought_signature; the openai_compatible shim cannot carry
# thoughtSignature through the wire format Gemini's OpenAI-compatible
# endpoint expects, which is why plain chat works there but tool
# calling fails with "Function call is missing a thought_signature in
# functionCall parts.")
# ---------------------------------------------------------------------------


def google_api_key() -> str:
    """CKS_GOOGLE_API_KEY takes precedence; GOOGLE_API_KEY (the name the
    official Google GenAI SDK / AI Studio docs use) is accepted as a
    fallback so users who already have that env var set elsewhere don't
    have to set a second, CKS-prefixed one too."""
    return os.environ.get("CKS_GOOGLE_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def google_base_url() -> str:
    return os.environ.get(
        "CKS_GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")


def _to_google_tools(tools: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped tool specs into Gemini's
    functionDeclarations shape."""
    return [
        {
            "functionDeclarations": [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                }
                for t in tools
            ]
        }
    ]


def _to_google_contents(messages: list[dict]) -> tuple[list[dict], str]:
    """Translate Anthropic-shaped messages into Gemini's ``contents``
    list (role: 'user' | 'model', parts: [{text}|{functionCall}|
    {functionResponse}]), plus any leading system-role message pulled
    out separately (Gemini takes system instructions via a dedicated
    ``systemInstruction`` field, not as a content turn).

    When a prior ``tool_use`` block carries a ``_google_thought_signature``
    key (stashed there by ``_from_google_response`` below), it's echoed
    back on the corresponding functionCall part -- Gemini's thinking
    models require the original thought signature to be replayed
    alongside a function call when it reappears in history, or the next
    turn fails with the same "missing a thought_signature" error this
    provider exists to fix.
    """
    system_parts: list[str] = []
    contents: list[dict] = []

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")

        if role == "system":
            system_parts.append(content if isinstance(content, str) else json.dumps(content))
            continue

        google_role = "model" if role == "assistant" else "user"

        if isinstance(content, str):
            contents.append({"role": google_role, "parts": [{"text": content}]})
            continue

        parts: list[dict] = []
        for block in content or []:
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    parts.append({"text": text})
            elif btype == "tool_use":
                fn_call: dict[str, Any] = {
                    "name": block.get("name", ""),
                    "args": block.get("input") or {},
                }
                part: dict[str, Any] = {"functionCall": fn_call}
                sig = block.get("_google_thought_signature")
                if sig:
                    part["thoughtSignature"] = sig
                parts.append(part)
            elif btype == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    try:
                        result_content = json.loads(result_content)
                    except json.JSONDecodeError:
                        result_content = {"result": result_content}
                if not isinstance(result_content, dict):
                    result_content = {"result": result_content}
                parts.append(
                    {
                        "functionResponse": {
                            "name": block.get("_google_tool_name", ""),
                            "response": result_content,
                        }
                    }
                )

        if parts:
            contents.append({"role": google_role, "parts": parts})

    return contents, "\n".join(system_parts)


def _from_google_response(body: dict) -> dict:
    """Translate a Gemini ``generateContent`` response into the same
    {'content': [block, ...]} envelope call_anthropic_with_tools
    returns.

    Each functionCall part's ``thoughtSignature`` (when present) is
    stashed on the resulting tool_use block as ``_google_thought_signature``
    so ``_to_google_contents`` can replay it if/when this turn is sent
    back as history -- see that function's docstring.
    """
    candidates = body.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") if candidates else None) or []

    content: list[dict] = []
    for i, part in enumerate(parts):
        if part.get("text"):
            content.append({"type": "text", "text": part["text"]})
        elif "functionCall" in part:
            call = part["functionCall"] or {}
            block: dict[str, Any] = {
                "type": "tool_use",
                "id": call.get("id") or f"google_tool_{i}",
                "name": call.get("name", ""),
                "input": call.get("args") or {},
                # Internal bookkeeping fields, not part of the public
                # Anthropic block shape -- round-tripped opaquely by
                # ai_chat's message history so a follow-up turn can
                # supply them back to Gemini (see _to_google_contents).
                "_google_tool_name": call.get("name", ""),
            }
            sig = part.get("thoughtSignature")
            if sig:
                block["_google_thought_signature"] = sig
            content.append(block)

    if not content:
        content.append({"type": "text", "text": ""})

    return {"content": content}


def call_google_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    max_tokens: int = 4096,
    tool_name: str | None = None,
) -> dict:
    """POSTs to Gemini's native ``generateContent`` endpoint with
    ``tools``/functionDeclarations, mirroring
    ``call_anthropic_with_tools``'s contract: returns ``{'content':
    [block, ...]}`` so ai_chat's loop is provider-agnostic. Uses the
    native Gemini API (not the OpenAI-compatible shim) specifically so
    ``thoughtSignature`` round-trips correctly on function-calling
    turns -- the OpenAI-compatible endpoint drops it, which is what
    causes "Function call is missing a thought_signature in
    functionCall parts." Raises RuntimeError with a descriptive,
    actionable message on any failure, same convention as
    ``call_anthropic_with_tools`` / ``call_openai_compatible_with_tools``.
    """
    import urllib.error
    import urllib.request

    api_key = google_api_key()
    if not api_key:
        raise RuntimeError(
            "CKS_GOOGLE_API_KEY (or GOOGLE_API_KEY) environment variable is not set. "
            "This tool requires a Google AI Studio API key to use the 'google' provider."
        )

    base_url = google_base_url()
    resolved_model = model or os.environ.get("CKS_GOOGLE_MODEL", "gemini-2.5-flash")

    contents, system_instruction = _to_google_contents(messages)
    payload: dict[str, Any] = {
        "contents": contents,
        "tools": _to_google_tools(tools),
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    encoded = json.dumps(payload).encode()
    url = f"{base_url}/models/{resolved_model}:generateContent"
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    approx_input_text = json.dumps(contents)

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Google Gemini call ({resolved_model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(
            f"Google Gemini API returned HTTP {exc.code}: {raw[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(f"Network error calling Google Gemini API: {exc.reason}") from exc

    if "candidates" not in body or not body["candidates"]:
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=resolved_model,
                tool=tool_name,
                tokens=estimate_tokens_from_chars(approx_input_text),
                start=start,
                success=False,
                error_type="NoCandidates",
            )
        raise RuntimeError(f"Google Gemini API returned no 'candidates'. Full response: {body}")

    result = _from_google_response(body)

    usage = body.get("usageMetadata") or {}
    tokens = int(usage.get("totalTokenCount") or 0)
    if not tokens:
        output_text = "".join(
            b.get("text", "") for b in result["content"] if b.get("type") == "text"
        )
        tokens = estimate_tokens_from_chars(approx_input_text + output_text)

    if tool_name is not None:
        _record_llm_call(
            provider="google",
            model=resolved_model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
        )

    return result


def call_google(
    prompt: str,
    *,
    system_prompt: str,
    model: str,
    max_tokens: int,
    tool_name: str | None = None,
) -> str:
    """Call Gemini's native ``generateContent`` endpoint synchronously,
    single-shot text-in/text-out (no tools) -- the same contract
    ``call_ollama``/``call_anthropic``/``call_openai_compatible_single_shot``
    already provide for ``construct_knowledge`` and ``ingest_document``'s
    ``use_llm`` mode. Raises ``RuntimeError`` with a descriptive message
    on any failure, same convention as the other single-shot callers.
    """
    import urllib.error
    import urllib.request

    api_key = google_api_key()
    if not api_key:
        raise RuntimeError(
            "CKS_GOOGLE_API_KEY (or GOOGLE_API_KEY) environment variable is not set. "
            "This tool requires a Google AI Studio API key to use the 'google' provider."
        )

    base_url = google_base_url()

    payload = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
    ).encode()

    url = f"{base_url}/models/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    def _do_request() -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    start = time.monotonic()
    try:
        body = call_with_retry(_do_request, call_label=f"Google Gemini call ({model})")
    except urllib.error.HTTPError as exc:
        raw = scrub_secrets(exc.read().decode(errors="replace"))
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(f"Google Gemini API returned HTTP {exc.code}: {raw[:400]}") from exc
    except urllib.error.URLError as exc:
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=model,
                tool=tool_name,
                tokens=0,
                start=start,
                success=False,
                error_type=type(exc).__name__,
            )
        raise RuntimeError(f"Network error calling Google Gemini API: {exc.reason}") from exc

    candidates = body.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") if candidates else None) or []
    text = "".join(p.get("text", "") for p in parts if "text" in p)

    usage = body.get("usageMetadata") or {}
    tokens = int(usage.get("totalTokenCount") or 0)
    if not tokens:
        tokens = estimate_tokens_from_chars(system_prompt + prompt + text)

    if not text:
        if tool_name is not None:
            _record_llm_call(
                provider="google",
                model=model,
                tool=tool_name,
                tokens=tokens,
                start=start,
                success=False,
                error_type="EmptyResponse",
            )
        raise RuntimeError(f"Google Gemini API returned no text. Full response: {body}")

    if tool_name is not None:
        _record_llm_call(
            provider="google",
            model=model,
            tool=tool_name,
            tokens=tokens,
            start=start,
            success=True,
        )

    return text


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