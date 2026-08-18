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
    google_fn=None,
    single_shot_ollama_fn=None,
    single_shot_anthropic_fn=None,
    single_shot_openai_compatible_fn=None,
    single_shot_google_fn=None,
) -> LLMClient:
    return LLMClient(
        anthropic_fn=anthropic_fn or MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]}),
        ollama_fn=ollama_fn or MagicMock(return_value={"content": [{"type": "text", "text": "ollama"}]}),
        openai_compatible_fn=openai_compatible_fn
        or MagicMock(return_value={"content": [{"type": "text", "text": "openai_compatible"}]}),
        google_fn=google_fn or MagicMock(return_value={"content": [{"type": "text", "text": "google"}]}),
        ollama_available_fn=MagicMock(return_value=ollama_available),
        single_shot_ollama_fn=single_shot_ollama_fn or MagicMock(return_value="ollama text"),
        single_shot_anthropic_fn=single_shot_anthropic_fn or MagicMock(return_value="anthropic text"),
        single_shot_openai_compatible_fn=single_shot_openai_compatible_fn
        or MagicMock(return_value="openai_compatible text"),
        single_shot_google_fn=single_shot_google_fn or MagicMock(return_value="google text"),
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
    assert client._single_shot_ollama_fn is llm_providers.call_ollama
    assert client._single_shot_anthropic_fn is llm_providers.call_anthropic
    assert (
        client._single_shot_openai_compatible_fn
        is llm_providers.call_openai_compatible_single_shot
    )
    assert client._google_fn is llm_providers.call_google_with_tools
    assert client._single_shot_google_fn is llm_providers.call_google


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


# ---------------------------------------------------------------------------
# google provider
# ---------------------------------------------------------------------------


def test_explicit_google_calls_google_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock()
    google_fn = MagicMock(return_value={"content": [{"type": "text", "text": "google"}]})
    client = _client(anthropic_fn=anthropic_fn, ollama_fn=ollama_fn, google_fn=google_fn)

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "google"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS, tool_name="ai_chat")

    assert result["content"][0]["text"] == "google"
    google_fn.assert_called_once()
    ollama_fn.assert_not_called()
    anthropic_fn.assert_not_called()


def test_auto_never_selects_google_when_ollama_unavailable():
    # Same rationale as openai_compatible: 'auto' must never silently
    # pick google, since choosing it over an explicitly configured
    # ANTHROPIC_API_KEY would be surprising.
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "anthropic"}]})
    google_fn = MagicMock()
    client = _client(
        ollama_available=False,
        anthropic_fn=anthropic_fn,
        ollama_fn=ollama_fn,
        google_fn=google_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}):
        result = client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert result["content"][0]["text"] == "anthropic"
    google_fn.assert_not_called()


def test_google_model_env_override_is_passed_through():
    google_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(google_fn=google_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "google", "CKS_GOOGLE_MODEL": "gemini-2.5-pro"},
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert google_fn.call_args.kwargs["model"] == "gemini-2.5-pro"


def test_call_with_tools_explicit_model_overrides_env_default_google():
    google_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(google_fn=google_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "google", "CKS_GOOGLE_MODEL": "gemini-2.5-flash"},
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS, model="gemini-2.5-pro")

    assert google_fn.call_args.kwargs["model"] == "gemini-2.5-pro"


def test_unknown_provider_message_mentions_google():
    client = _client()
    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "bogus"}),
        pytest.raises(RuntimeError, match="google"),
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)


# ---------------------------------------------------------------------------
# call_with_tools: explicit per-call 'model' override (cks-studio Settings
# -> AI & LLM "Preferred model" -> ai_chat's optional 'model' argument)
# ---------------------------------------------------------------------------


def test_call_with_tools_explicit_model_overrides_env_default_ollama():
    ollama_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(ollama_fn=ollama_fn)

    with patch.dict(
        "os.environ", {"CKS_LLM_PROVIDER": "ollama", "CKS_OLLAMA_MODEL": "llama3.2"}
    ):
        client.call_with_tools(
            messages=MESSAGES,
            tools=TOOLS,
            model="nvidia/nemotron-3-super-120b-a12b:free",
        )

    assert (
        ollama_fn.call_args.kwargs["model"]
        == "nvidia/nemotron-3-super-120b-a12b:free"
    )


def test_call_with_tools_explicit_model_overrides_env_default_anthropic():
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(anthropic_fn=anthropic_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "anthropic", "CKS_ANTHROPIC_MODEL": "claude-sonnet-4-6"},
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS, model="claude-opus-4-8")

    assert anthropic_fn.call_args.kwargs["model"] == "claude-opus-4-8"


def test_call_with_tools_explicit_model_overrides_env_default_openai_compatible():
    openai_compatible_fn = MagicMock(
        return_value={"content": [{"type": "text", "text": "ok"}]}
    )
    client = _client(openai_compatible_fn=openai_compatible_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "openai_compatible", "CKS_OPENAI_MODEL": "gpt-4o"},
    ):
        client.call_with_tools(
            messages=MESSAGES,
            tools=TOOLS,
            model="nvidia/nemotron-3-super-120b-a12b:free",
        )

    assert (
        openai_compatible_fn.call_args.kwargs["model"]
        == "nvidia/nemotron-3-super-120b-a12b:free"
    )


def test_call_with_tools_no_model_override_falls_back_to_env():
    # Omitting 'model' (the default) must not change any existing
    # behavior -- the env var still wins, same as before this argument
    # existed.
    anthropic_fn = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
    client = _client(anthropic_fn=anthropic_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "anthropic", "CKS_ANTHROPIC_MODEL": "claude-sonnet-4-6"},
    ):
        client.call_with_tools(messages=MESSAGES, tools=TOOLS)

    assert anthropic_fn.call_args.kwargs["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# call_single_shot: explicit provider selection
# ---------------------------------------------------------------------------


def test_single_shot_explicit_ollama_calls_ollama_fn_only():
    ollama_fn = MagicMock(return_value="ollama text")
    anthropic_fn = MagicMock()
    openai_compatible_fn = MagicMock()
    client = _client(
        single_shot_ollama_fn=ollama_fn,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_openai_compatible_fn=openai_compatible_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "ollama"}, clear=True):
        text, model = client.call_single_shot(
            "hi", system_prompt="sys", max_tokens=100, tool_name="construct_knowledge"
        )

    assert (text, model) == ("ollama text", "llama3.2")
    ollama_fn.assert_called_once_with(
        "hi", system_prompt="sys", model="llama3.2", max_tokens=100, tool_name="construct_knowledge"
    )
    anthropic_fn.assert_not_called()
    openai_compatible_fn.assert_not_called()


def test_single_shot_explicit_anthropic_calls_anthropic_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value="anthropic text")
    openai_compatible_fn = MagicMock()
    client = _client(
        single_shot_ollama_fn=ollama_fn,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_openai_compatible_fn=openai_compatible_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "anthropic"}, clear=True):
        text, model = client.call_single_shot("hi", system_prompt="sys", max_tokens=100)

    assert (text, model) == ("anthropic text", "claude-sonnet-4-6")
    anthropic_fn.assert_called_once()
    ollama_fn.assert_not_called()
    openai_compatible_fn.assert_not_called()


def test_single_shot_explicit_openai_compatible_calls_openai_compatible_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock()
    openai_compatible_fn = MagicMock(return_value="openai_compatible text")
    client = _client(
        single_shot_ollama_fn=ollama_fn,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_openai_compatible_fn=openai_compatible_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "openai_compatible"}, clear=True):
        text, model = client.call_single_shot("hi", system_prompt="sys", max_tokens=100)

    assert (text, model) == ("openai_compatible text", "gpt-4o")
    openai_compatible_fn.assert_called_once_with(
        "hi", system_prompt="sys", model="gpt-4o", max_tokens=100, tool_name=None
    )
    ollama_fn.assert_not_called()
    anthropic_fn.assert_not_called()


def test_single_shot_explicit_google_calls_google_fn_only():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock()
    google_fn = MagicMock(return_value="google text")
    client = _client(
        single_shot_ollama_fn=ollama_fn,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_google_fn=google_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "google"}, clear=True):
        text, model = client.call_single_shot("hi", system_prompt="sys", max_tokens=100)

    assert (text, model) == ("google text", "gemini-2.5-flash")
    google_fn.assert_called_once_with(
        "hi", system_prompt="sys", model="gemini-2.5-flash", max_tokens=100, tool_name=None
    )
    ollama_fn.assert_not_called()
    anthropic_fn.assert_not_called()


def test_single_shot_unknown_provider_raises_plain_runtime_error():
    client = _client()
    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "bogus"}, clear=True),
        pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER"),
    ):
        client.call_single_shot("hi", system_prompt="sys")


# ---------------------------------------------------------------------------
# call_single_shot: 'auto' provider selection
# ---------------------------------------------------------------------------


def test_single_shot_auto_prefers_ollama_when_available():
    ollama_fn = MagicMock(return_value="ollama text")
    anthropic_fn = MagicMock()
    client = _client(
        ollama_available=True, single_shot_ollama_fn=ollama_fn, single_shot_anthropic_fn=anthropic_fn
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True):
        text, _ = client.call_single_shot("hi", system_prompt="sys")

    assert text == "ollama text"
    anthropic_fn.assert_not_called()


def test_single_shot_auto_falls_back_to_anthropic_when_ollama_unavailable():
    ollama_fn = MagicMock()
    anthropic_fn = MagicMock(return_value="anthropic text")
    client = _client(
        ollama_available=False, single_shot_ollama_fn=ollama_fn, single_shot_anthropic_fn=anthropic_fn
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True):
        text, _ = client.call_single_shot("hi", system_prompt="sys")

    assert text == "anthropic text"
    ollama_fn.assert_not_called()


def test_single_shot_auto_never_selects_openai_compatible_when_ollama_unavailable():
    anthropic_fn = MagicMock(return_value="anthropic text")
    openai_compatible_fn = MagicMock()
    client = _client(
        ollama_available=False,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_openai_compatible_fn=openai_compatible_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True):
        text, _ = client.call_single_shot("hi", system_prompt="sys")

    assert text == "anthropic text"
    openai_compatible_fn.assert_not_called()


def test_single_shot_auto_never_selects_google_when_ollama_unavailable():
    anthropic_fn = MagicMock(return_value="anthropic text")
    google_fn = MagicMock()
    client = _client(
        ollama_available=False,
        single_shot_anthropic_fn=anthropic_fn,
        single_shot_google_fn=google_fn,
    )

    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True):
        text, _ = client.call_single_shot("hi", system_prompt="sys")

    assert text == "anthropic text"
    google_fn.assert_not_called()


def test_single_shot_auto_raises_llm_provider_unavailable_when_nothing_works():
    anthropic_fn = MagicMock(side_effect=RuntimeError("ANTHROPIC_API_KEY not set"))
    client = _client(ollama_available=False, single_shot_anthropic_fn=anthropic_fn)

    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True),
        pytest.raises(LLMProviderUnavailable),
    ):
        client.call_single_shot("hi", system_prompt="sys")


def test_single_shot_auto_reraises_non_api_key_anthropic_errors_as_plain_runtime_error():
    anthropic_fn = MagicMock(side_effect=RuntimeError("some other failure"))
    client = _client(ollama_available=False, single_shot_anthropic_fn=anthropic_fn)

    with (
        patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}, clear=True),
        pytest.raises(RuntimeError) as exc_info,
    ):
        client.call_single_shot("hi", system_prompt="sys")

    assert not isinstance(exc_info.value, LLMProviderUnavailable)


# ---------------------------------------------------------------------------
# call_single_shot: model resolution
# ---------------------------------------------------------------------------


def test_single_shot_explicit_model_overrides_env_default():
    ollama_fn = MagicMock(return_value="ollama text")
    client = _client(single_shot_ollama_fn=ollama_fn)

    with patch.dict(
        "os.environ", {"CKS_LLM_PROVIDER": "ollama", "CKS_OLLAMA_MODEL": "qwen2.5:7b"}, clear=True
    ):
        _, model = client.call_single_shot("hi", system_prompt="sys", model="llama3.1")

    assert model == "llama3.1"
    assert ollama_fn.call_args.kwargs["model"] == "llama3.1"


def test_single_shot_ollama_model_env_override_is_passed_through():
    ollama_fn = MagicMock(return_value="ollama text")
    client = _client(single_shot_ollama_fn=ollama_fn)

    with patch.dict(
        "os.environ", {"CKS_LLM_PROVIDER": "ollama", "CKS_OLLAMA_MODEL": "qwen2.5:7b"}, clear=True
    ):
        _, model = client.call_single_shot("hi", system_prompt="sys")

    assert model == "qwen2.5:7b"


def test_single_shot_openai_compatible_model_env_override_is_passed_through():
    openai_compatible_fn = MagicMock(return_value="ok")
    client = _client(single_shot_openai_compatible_fn=openai_compatible_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "openai_compatible", "CKS_OPENAI_MODEL": "deepseek-chat"},
        clear=True,
    ):
        _, model = client.call_single_shot("hi", system_prompt="sys")

    assert model == "deepseek-chat"


def test_single_shot_google_model_env_override_is_passed_through():
    google_fn = MagicMock(return_value="ok")
    client = _client(single_shot_google_fn=google_fn)

    with patch.dict(
        "os.environ",
        {"CKS_LLM_PROVIDER": "google", "CKS_GOOGLE_MODEL": "gemini-2.5-pro"},
        clear=True,
    ):
        _, model = client.call_single_shot("hi", system_prompt="sys")

    assert model == "gemini-2.5-pro"