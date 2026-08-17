"""Unit tests for the ai_chat MCP tool (cks-mcp ADR-011)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.tools.ai_chat.handler import ai_chat

pytestmark = pytest.mark.asyncio


def _text_response(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _tool_use_response(tool_name: str, tool_args: dict, tool_use_id: str = "toolu_1") -> dict:
    return {
        "content": [
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": tool_name,
                "input": tool_args,
            }
        ]
    }


FAKE_TOOLS = {
    "query_subgraph": {
        "description": "Read the graph.",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}},
        "handler": AsyncMock(return_value={"objects": []}),
    },
    "evolve_knowledge": {
        "description": "Mutate the graph.",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}},
        "handler": AsyncMock(return_value={"session_id": "s1", "version_id": "v2"}),
    },
    "export_storage": {
        "description": "Back up all storage.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": AsyncMock(return_value={"ok": True}),
    },
}


@pytest.fixture(autouse=True)
def patched_registry():
    with patch("cks_mcp.registry.TOOLS", FAKE_TOOLS):
        yield


async def test_simple_reply_with_no_tool_calls():
    runtime = MagicMock()
    with patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        return_value=_text_response("Hello there."),
    ):
        result = await ai_chat(
            runtime, {"session_id": "s1", "prompt": "hi"}
        )

    assert result["reply"] == "Hello there."
    assert result["tool_calls"] == []
    # messages grew by exactly one assistant turn on top of the user turn.
    assert result["messages"][0] == {"role": "user", "content": "hi"}
    assert result["messages"][1]["role"] == "assistant"


async def test_session_id_is_pinned_even_if_llm_supplies_another():
    runtime = MagicMock()
    responses = [
        _tool_use_response("query_subgraph", {"session_id": "attacker-session"}),
        _text_response("Done."),
    ]
    with patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=responses,
    ):
        result = await ai_chat(
            runtime, {"session_id": "s1", "prompt": "read the graph"}
        )

    assert result["tool_calls"][0]["arguments"]["session_id"] == "s1"
    FAKE_TOOLS["query_subgraph"]["handler"].assert_awaited()
    called_args = FAKE_TOOLS["query_subgraph"]["handler"].call_args.args[1]
    assert called_args["session_id"] == "s1"


async def test_disallowed_tool_is_reported_as_error_not_executed():
    runtime = MagicMock()
    responses = [
        _tool_use_response("export_storage", {}),
        _text_response("Can't do that."),
    ]
    with patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=responses,
    ):
        result = await ai_chat(
            runtime, {"session_id": "s1", "prompt": "back everything up"}
        )

    call = result["tool_calls"][0]
    assert call["name"] == "export_storage"
    assert call["is_error"] is True
    assert call["result"]["error"] == "unknown_or_disallowed_tool"


async def test_handler_exception_becomes_tool_result_error_not_raised():
    runtime = MagicMock()
    broken_tools = dict(FAKE_TOOLS)
    broken_tools["evolve_knowledge"] = {
        **FAKE_TOOLS["evolve_knowledge"],
        "handler": AsyncMock(side_effect=RuntimeError("boom")),
    }
    responses = [
        _tool_use_response("evolve_knowledge", {"session_id": "s1"}),
        _text_response("It failed."),
    ]
    with patch("cks_mcp.registry.TOOLS", broken_tools), patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=responses,
    ):
        result = await ai_chat(
            runtime, {"session_id": "s1", "prompt": "evolve it"}
        )

    assert result["reply"] == "It failed."
    assert result["tool_calls"][0]["is_error"] is True
    assert "boom" in result["tool_calls"][0]["result"]["error"]


async def test_iteration_cap_returns_clear_message_not_infinite_loop():
    runtime = MagicMock()
    with patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        return_value=_tool_use_response("query_subgraph", {}),
    ) as mock_call:
        result = await ai_chat(
            runtime, {"session_id": "s1", "prompt": "loop forever"}
        )

    assert mock_call.call_count == 8  # _MAX_ITERATIONS
    assert "iteration limit" in result["reply"]
    # Structured flag so callers can detect this retriable condition
    # without string-matching the reply text (see handler comment).
    assert result["truncated"] is True


def _ollama_tool_use_response(tool_name: str, tool_args: dict, call_id: str = "call_1") -> dict:
    """As returned by call_ollama_with_tools -- already normalized into
    the same {'content': [...]} envelope call_anthropic_with_tools
    returns, since that normalization is call_ollama_with_tools's own
    job (tested separately in test_llm_providers.py)."""
    return {
        "content": [
            {"type": "tool_use", "id": call_id, "name": tool_name, "input": tool_args}
        ]
    }


async def test_ai_chat_uses_ollama_when_provider_is_explicitly_ollama():
    runtime = MagicMock()
    responses = [
        _ollama_tool_use_response("query_subgraph", {}),
        _text_response("Done via Ollama."),
    ]
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "ollama"}), patch(
        "cks_mcp.tools.ai_chat.handler.call_ollama_with_tools", side_effect=responses
    ) as mock_ollama, patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools"
    ) as mock_anthropic:
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "read the graph"})

    assert result["reply"] == "Done via Ollama."
    mock_anthropic.assert_not_called()
    assert mock_ollama.call_count == 2


async def test_ai_chat_auto_prefers_ollama_when_available():
    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}), patch(
        "cks_mcp.tools.ai_chat.handler.ollama_available", return_value=True
    ), patch(
        "cks_mcp.tools.ai_chat.handler.call_ollama_with_tools",
        return_value=_text_response("Hi from local model."),
    ) as mock_ollama, patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools"
    ) as mock_anthropic:
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["reply"] == "Hi from local model."
    mock_ollama.assert_called_once()
    mock_anthropic.assert_not_called()


async def test_ai_chat_auto_falls_back_to_anthropic_when_ollama_unreachable():
    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto", "ANTHROPIC_API_KEY": "sk-test"}), patch(
        "cks_mcp.tools.ai_chat.handler.ollama_available", return_value=False
    ), patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        return_value=_text_response("Hi from Anthropic."),
    ) as mock_anthropic, patch(
        "cks_mcp.tools.ai_chat.handler.call_ollama_with_tools"
    ) as mock_ollama:
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["reply"] == "Hi from Anthropic."
    mock_ollama.assert_not_called()
    mock_anthropic.assert_called_once()


async def test_missing_prompt_and_messages_returns_missing_parameter():
    runtime = MagicMock()
    result = await ai_chat(runtime, {"session_id": "s1"})
    assert result["error"] == "missing_parameter"


async def test_llm_call_failure_is_reported_not_raised():
    # Provider forced to 'anthropic' so a non-ANTHROPIC_API_KEY failure
    # (e.g. a transient HTTP error) surfaces as a plain llm_call_failed
    # rather than being reinterpreted as "no provider available at
    # all" (see test_no_provider_available_returns_llm_provider_unavailable
    # below for that case).
    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "anthropic"}), patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=RuntimeError("Anthropic API returned HTTP 529: overloaded"),
    ):
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["error"] == "llm_call_failed"
    assert "overloaded" in result["message"]


async def test_no_provider_available_returns_llm_provider_unavailable():
    # 'auto' with Ollama unreachable and no ANTHROPIC_API_KEY: neither
    # provider can serve the call, so this is reported with a distinct
    # error code rather than crashing or looking like a normal
    # transient llm_call_failed.
    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "auto"}), patch(
        "cks_mcp.tools.ai_chat.handler.ollama_available", return_value=False
    ), patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set."),
    ):
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["error"] == "llm_provider_unavailable"
    assert "ollama" in result["message"].lower()
    assert "anthropic" in result["message"].lower()


async def test_model_argument_is_forwarded_to_the_provider_call():
    # A caller-supplied 'model' (e.g. cks-studio's Settings -> AI & LLM
    # "Preferred model" field) must reach the provider call as an
    # explicit override, without needing any server env var changed.
    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "anthropic"}, clear=False), patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        return_value=_text_response("Hi from a custom model."),
    ) as mock_call:
        result = await ai_chat(
            runtime,
            {
                "session_id": "s1",
                "prompt": "hi",
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
            },
        )

    assert result["reply"] == "Hi from a custom model."
    assert (
        mock_call.call_args.kwargs["model"]
        == "nvidia/nemotron-3-super-120b-a12b:free"
    )


async def test_omitted_model_argument_falls_back_to_provider_default():
    # No 'model' in arguments -- and no CKS_ANTHROPIC_MODEL env var --
    # means the provider call gets no explicit 'model' kwarg at all,
    # same behavior as before 'model' passthrough existed.
    import os as _os

    runtime = MagicMock()
    with patch.dict("os.environ", {"CKS_LLM_PROVIDER": "anthropic"}, clear=False):
        _os.environ.pop("CKS_ANTHROPIC_MODEL", None)
        with patch(
            "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
            return_value=_text_response("Hi."),
        ) as mock_call:
            result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["reply"] == "Hi."
    assert "model" not in mock_call.call_args.kwargs
