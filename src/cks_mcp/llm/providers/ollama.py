"""
Ollama provider primitives (local, no API key) -- generate + chat/tools.
"""

from __future__ import annotations

import json
import os
import time

from cks_mcp.llm.providers._shared import _record_llm_call
from cks_mcp.llm.redact import scrub_secrets
from cks_mcp.llm.retry import call_with_retry
from cks_mcp.observability.llm_telemetry import estimate_tokens_from_chars

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
