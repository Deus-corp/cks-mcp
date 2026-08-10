"""Unit tests for ``cks_mcp.llm.client.LLMClient`` (cks-mcp ADR-011 §6).

Provider functions are injected as plain fakes here (not patched via
``unittest.mock.patch`` against ``llm_providers``) since ``LLMClient``
takes them as constructor args -- this file tests the *routing* logic
in isolation from the HTTP plumbing, which is covered separately in
test_llm_providers.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.llm.client import LLMClient, LLMProviderUnavailable

MESSAGES = [{"role": "user", "content": "hi"}]
TOOLS = [{"name": "noop", "description": "does nothing", "input_schema": {"type": "object"}}]


def _client(
    *,
    ollama_available: bool = False,
    anthropic_fn=None,
    ollama_fn=None,
    openai_compatible_fn=None,
) -> LLMClient:
    return LLMClient(
        anthropic_fn=anthropic_fn or MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]}),
        ollama_fn=ollama_fn or MagicMock(return_value={"content": [{"type": "text", "text": "ollama"}]}),
        openai_compatible_fn=openai_compatible_fn
        or MagicMock(return_value={"content": [{"type": "text", "text": "openai_compatible"}]}),
        ollama_available_fn=MagicMock(return_value=ollama_available),
    )


# ---------------------------------------------------------------------------
# Explicit provider selection
# ---------------------------------------------------------------------------


def test_explicit_ollama_calls_ollama_fn_only():
    ollama_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ollama"}]})
    anthropic_fn = MagicMock()
    client = _client(anthropic_fn=anthropic_fn, ollama_fn=ollama_fn)

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "ollama"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS, tool_name="ai_chat")

    assert result["content"][0]["text"] == "ollama"
    ollama_fn.assert_called_once()
    anthropic_fn.assert_not_called()


def test_explicit_anthropic_calls_anthropic_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]})
    client = _client(anthropic_fn=anthropic_fn, ollama_fn=ollama_fn)

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "anthropic"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS, tool_name="ai_chat")

    assert result["content"][0]["text"] == "anthropic"
    anthropic_fn.assert_called_once()
    ollama_fn.assert_not_called()


def test_unknown_provider_raises_plain_runtime_error():
    client = _client()
    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "bogus"}),
        pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER"),
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)


# ---------------------------------------------------------------------------
# 'auto' provider selection
# ---------------------------------------------------------------------------


def test_auto_prefers_ollama_when_available():
    ollama_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ollama"}]})
    anthropic_fn = MagicMock()
    client = _client(ollama_available=True, anthropic_fn=anthropic_fn, ollama_fn=ollama_fn)

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert result["content"][0]["text"] == "ollama"
    anthropic_fn.assert_not_called()


def test_auto_falls_back_to_anthropic_when_ollama_unavailable():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]})
    client = _client(ollama_available=False, anthropic_fn=anthropic_fn, ollama_fn=ollama_fn)

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert result["content"][0]["text"] == "anthropic"
    ollama_fn.assert_not_called()


def test_auto_raises_llm_provider_unavailable_when_nothing_works():
    anthropic_fn = MagicMock(
        side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
    )
    client = _client(ollama_available=False, anthropic_fn=anthropic_fn)

    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=False),
        pytest.raises(LLMProviderUnavailable) as exc_info,
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert "ollama" in str(exc_info.value).lower()
    assert "anthropic" in str(exc_info.value).lower()


def test_auto_reraises_non_api_key_anthropic_errors_as_plain_runtime_error():
    # Anthropic reachable/configured but erroring for an unrelated
    # reason (e.g. rate limit) shouldn't be relabeled as "no provider
    # available at all".
    anthropic_fn = MagicMock(side_effect=RuntimeError("Anthropic API returned HTTP 429"))
    client = _client(ollama_available=False, anthropic_fn=anthropic_fn)

    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}),
        pytest.raises(RuntimeError) as exc_info,
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert not isinstance(exc_info.value, LLMProviderUnavailable)
    assert "429" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def test_ollama_model_env_override_is_passed_through():
    ollama_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(ollama_fn=ollama_fn)

    with patch.dict(
        "os.environ", {"CKS_LLM_PROVIDER": "ollama", "CKS_OLLAMA_MODEL": "qwen2.5:7b"}
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert ollama_fn.call_args.kwargs["model"] == "qwen2.5:7b"


def test_default_construction_uses_real_llm_providers_functions():
    # Sanity check that the production constructor defaults actually
    # point at llm_providers' real functions, not e.g. None -- a
    # regression here would only be caught by a wiring test like this
    # one, since every other test in this file injects fakes.
    from cks_mcp import llm_providers

    client = LLMClient()
    assert client._anthropic_fn is llm_providers.call_anthropic_with_tools
    assert client._ollama_fn is llm_providers.call_ollama_with_tools
    assert client._openai_compatible_fn is llm_providers.call_openai_compatible_with_tools
    assert client._ollama_available_fn is llm_providers.ollama_available


# ---------------------------------------------------------------------------
# openai_compatible provider
# ---------------------------------------------------------------------------


def test_explicit_openai_compatible_calls_openai_compatible_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock()
    openai_compatible_fn = MagicMock(
        return_value={"content": [{"type": "text", "text": "openai_compatible"}]}
    )
    client = _client(
        anthropic_fn=anthropic_fn, ollama_fn=ollama_fn, openai_compatible_fn=openai_compatible_fn
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "openai_compatible"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS, tool_name="ai_chat")

    assert result["content"][0]["text"] == "openai_compatible"
    openai_compatible_fn.assert_called_once()
    ollama_fn.assert_not_called()
    anthropic_fn.assert_not_called()


def test_auto_never_selects_openai_compatible_when_ollama_unavailable():
    # 'auto' with Ollama unreachable must still fall through to
    # Anthropic (or raise LLMProviderUnavailable) -- it must never
    # silently pick openai_compatible, since its base URL/model/key
    # combination can't be guessed safely.
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]})
    openai_compatible_fn = MagicMock()
    client = _client(
        ollama_available=False,
        anthropic_fn=anthropic_fn,
        ollama_fn=ollama_fn,
        openai_compatible_fn=openai_compatible_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert result["content"][0]["text"] == "anthropic"
    openai_compatible_fn.assert_not_called()


def test_openai_compatible_model_env_override_is_passed_through():
    openai_compatible_fn = MagicMock(
        return_value={"content": [{"type": "text", "text": "ok"}]}
    )
    client = _client(openai_compatible_fn=openai_compatible_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "openai_compatible", "CKS_OPENAI_MODEL": "gpt-4o-mini"},
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert openai_compatible_fn.call_args.kwargs["model"] == "gpt-4o-mini"
