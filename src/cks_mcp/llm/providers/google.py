"""
Google Gemini provider primitives -- native API (not the
OpenAI-compatible shim), needed for correct tool-calling with
thoughtSignature preserved across turns (see call_google_with_tools).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from cks_mcp.llm.providers._shared import _record_llm_call
from cks_mcp.llm.redact import scrub_secrets
from cks_mcp.llm.retry import call_with_retry
from cks_mcp.observability.llm_telemetry import estimate_tokens_from_chars

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


# JSON Schema / OpenAPI keywords that Google's Gemini function-calling
# schema subset does not understand. Gemini returns HTTP 400 ("Unknown
# name ... Cannot find field") if any of these appear anywhere in a
# function declaration's `parameters`, even nested. These are stripped
# on the way out to Google only -- the source schemas (registry.TOOLS,
# MCP `inputSchema`) are left untouched, since other providers and
# strict-JSON-Schema consumers rely on them.
_GOOGLE_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "$schema",
        "$ref",
        "default",
        "examples",
        "const",
        "readOnly",
        "writeOnly",
        "deprecated",
    }
)

# Keywords Gemini's schema subset does understand and that we pass
# through as-is (after recursive normalization of their values).
_GOOGLE_SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "description",
        "enum",
        "properties",
        "items",
        "required",
        "nullable",
    }
)


def _normalize_schema_for_google(schema: Any) -> Any:
    """Recursively normalize a JSON Schema fragment so it satisfies
    Gemini's (stricter-than-JSON-Schema, and narrower-than-JSON-Schema)
    function-declaration validator.

    Known Gemini requirements this enforces:
      - Every ``"type": "array"`` node must have an ``"items"`` field,
        and that ``items`` value must itself declare a ``"type"``
        (a bare ``{}`` is rejected). Missing/empty ``items`` are
        defaulted to ``{"type": "object"}``, which is permissive
        enough to accept whatever shape the array elements actually
        have.
      - An object node with no ``"properties"`` key is normalized to
        ``properties: {}`` rather than left absent, since some Gemini
        versions reject an object type with neither ``properties`` nor
        ``additionalProperties`` set.
      - Keywords Gemini's schema subset doesn't recognize --
        ``additionalProperties``, ``$schema``, ``$ref``, ``default``,
        ``examples``, ``const``, ``readOnly``, ``writeOnly``,
        ``deprecated`` -- are dropped entirely (see
        ``_GOOGLE_UNSUPPORTED_KEYWORDS``). Gemini rejects the *whole*
        ``tools`` payload with HTTP 400 if even one function
        declaration contains an unrecognized field name, so this has
        to be thorough, not best-effort.
      - ``anyOf`` / ``oneOf`` / ``allOf`` compositions aren't supported
        by Gemini's schema subset either. Rather than trying to
        losslessly translate a union/intersection into Gemini's
        vocabulary, each is collapsed to the most permissive safe
        equivalent: an empty object schema (``{}``, i.e. "accept
        anything here"). This trades precision for validity -- Gemini
        will happily pass through a value that a stricter schema would
        have rejected, but that's preferable to the tool being
        unusable at all.

    Only dict/list structures are walked; anything else is returned
    unchanged. The input is not mutated -- a new structure is returned.
    """
    if isinstance(schema, dict):
        if any(k in schema for k in ("anyOf", "oneOf", "allOf")):
            # Most permissive safe equivalent: accept anything. We
            # still preserve a description if one was present, since
            # that's free-text documentation Gemini does support and
            # dropping it would lose useful context for the model.
            description = schema.get("description")
            return {"description": description} if description else {}

        result = {
            k: _normalize_schema_for_google(v)
            for k, v in schema.items()
            if k not in _GOOGLE_UNSUPPORTED_KEYWORDS
        }
        if result.get("type") == "array":
            items = result.get("items")
            if not isinstance(items, dict) or not items.get("type"):
                result["items"] = {"type": "object"}
        elif result.get("type") == "object" and "properties" not in result:
            result["properties"] = {}
        return result
    if isinstance(schema, list):
        return [_normalize_schema_for_google(v) for v in schema]
    return schema


def _to_google_tools(tools: list[dict]) -> list[dict]:
    """Translate Anthropic-shaped tool specs into Gemini's
    functionDeclarations shape.

    Schemas are run through ``_normalize_schema_for_google`` so that a
    tool whose ``input_schema`` has an array property with missing or
    empty ``items`` (valid JSON Schema, but rejected by Gemini's
    function-calling validator with e.g. "parameters.properties[x].items:
    missing field") doesn't break tool-calling for every tool in the
    same request -- Gemini rejects the entire ``tools`` list if any one
    function declaration is malformed.
    """
    return [
        {
            "functionDeclarations": [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _normalize_schema_for_google(
                        t.get("input_schema") or {"type": "object", "properties": {}}
                    ),
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

    ``tool_result`` blocks are expected to carry ``_google_tool_name``
    (stashed by the caller, e.g. ai_chat's tool loop, or round-tripped
    from a prior ``_from_google_response``). If a block is missing it --
    a caller-side bug, or a Anthropic-shaped history built without
    Google in mind -- the name is resolved by scanning back through
    earlier ``tool_use`` blocks in this same message list for one whose
    ``id`` matches the result's ``tool_use_id``. Google's API returns
    HTTP 400 ("Name cannot be empty") for a functionResponse with an
    empty name, so this lookup is a hard requirement, not a nicety.
    """
    system_parts: list[str] = []
    contents: list[dict] = []

    # tool_use_id -> tool name, gathered as we walk the messages so the
    # fallback lookup below always has everything seen so far available.
    tool_name_by_use_id: dict[str, str] = {}
    for m in messages:
        for block in (m.get("content") or []) if not isinstance(m.get("content"), str) else []:
            if block.get("type") == "tool_use" and block.get("id"):
                tool_name_by_use_id[block["id"]] = block.get("name", "")

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
                fn_name = block.get("_google_tool_name") or tool_name_by_use_id.get(
                    block.get("tool_use_id", ""), ""
                )
                parts.append(
                    {
                        "functionResponse": {
                            "name": fn_name,
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