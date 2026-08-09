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


async def test_missing_prompt_and_messages_returns_missing_parameter():
    runtime = MagicMock()
    result = await ai_chat(runtime, {"session_id": "s1"})
    assert result["error"] == "missing_parameter"


async def test_llm_call_failure_is_reported_not_raised():
    runtime = MagicMock()
    with patch(
        "cks_mcp.tools.ai_chat.handler.call_anthropic_with_tools",
        side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set."),
    ):
        result = await ai_chat(runtime, {"session_id": "s1", "prompt": "hi"})

    assert result["error"] == "llm_call_failed"
    assert "ANTHROPIC_API_KEY" in result["message"]
