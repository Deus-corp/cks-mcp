"""
OpenAI-compatible ``/chat/completions`` provider primitives -- used
by OpenAI, Groq, DeepSeek, Together, LM Studio, and any other backend
that speaks the OpenAI chat-completions wire format.
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
