"""Handler for the ai_chat tool (cks-mcp ADR-011 / cks-studio ADR-001).

Implements a bounded agentic loop over a tool-calling LLM: the LLM is
offered every registered tool except a small denylist of
server-management tools, may call them freely across up to
_MAX_ITERATIONS round-trips, and every session-shaped argument it
supplies is pinned to this call's own session_id before execution (see
ADR-011 §2/§3). The loop is stateless -- callers pass the full message
history each time and get the updated history back (ADR-011 §5 /
ADR-001 §2).

The LLM call itself is routed through ``cks_mcp.llm.client.LLMClient``,
which picks Ollama or Anthropic per ``CKS_LLM_PROVIDER`` -- the same
convention ``construct_knowledge`` uses (ADR-011 §6). Both providers'
tool-calling entry points return the same ``{'content': [block, ...]}``
envelope, so the loop below never branches on which one actually
answered.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.llm.client import LLMClient, LLMProviderUnavailable
from cks_mcp.llm.providers import (
    call_anthropic_with_tools,
    call_ollama_with_tools,
    ollama_available,
)

# Denylist, not allowlist: anything that manages the server/runtime
# itself (storage migration, plugin/process lifecycle, backup/restore)
# is never something a chat LLM should be able to invoke, no matter the
# prompt (see ADR-011 §1).
_DISALLOWED_TOOLS = {
    "migrate_storage",
    "export_storage",
    "import_storage",
    "list_plugins",
    "start_agent",
    "stop_agent",
    "request_process_stop",
    "register_graph",  # writes to the public gallery -- human-only for v1
}

# One round-trip to the LLM per iteration; an LLM stuck in a
# call-a-tool/re-evaluate cycle fails loudly instead of running up an
# unbounded number of Anthropic API calls (see ADR-011 §3).
_MAX_ITERATIONS = 8

# Tools whose arguments are session-scoped and must be pinned to the
# ai_chat caller's session_id before execution (see ADR-011 §2).
_SESSION_ARG_NAME = "session_id"


def _tool_specs_for_llm(tools: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": tool["description"],
            "input_schema": tool["inputSchema"],
        }
        for name, tool in tools.items()
        if name not in _DISALLOWED_TOOLS and name != "ai_chat"
    ]


async def ai_chat(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    # Imported lazily to avoid a circular import: registry.py imports
    # this module at startup to build TOOLS in the first place.
    from cks_mcp.registry import TOOLS

    session_id = arguments["session_id"]
    model_override = arguments.get("model") or None
    messages: list[dict[str, Any]] = list(arguments.get("messages") or [])
    if not messages:
        prompt = arguments.get("prompt")
        if not prompt:
            return {
                "error": "missing_parameter",
                "message": "Either 'messages' or 'prompt' must be provided.",
            }
        messages = [{"role": "user", "content": prompt}]

    tool_specs = _tool_specs_for_llm(TOOLS)
    executed_calls: list[dict[str, Any]] = []

    # Built fresh per call (not module-level) so it always picks up the
    # current provider functions -- including ones a test has patched
    # onto this module by name (see tests/tools/ai_chat/test_handler.py).
    llm_client = LLMClient(
        anthropic_fn=call_anthropic_with_tools,
        ollama_fn=call_ollama_with_tools,
        ollama_available_fn=ollama_available,
    )

    for _ in range(_MAX_ITERATIONS):
        try:
            response = llm_client.call_with_tools(
                messages=messages,
                tools=tool_specs,
                tool_name="ai_chat",
                model=model_override,
            )
        except LLMProviderUnavailable as exc:
            return {
                "error": "llm_provider_unavailable",
                "message": str(exc),
                "tool_calls": executed_calls,
                "messages": messages,
            }
        except RuntimeError as exc:
            return {
                "error": "llm_call_failed",
                "message": str(exc),
                "tool_calls": executed_calls,
                "messages": messages,
            }

        content = response.get("content", [])
        messages.append({"role": "assistant", "content": content})

        tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
        if not tool_use_blocks:
            reply = "".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
            return {"reply": reply, "tool_calls": executed_calls, "messages": messages}

        tool_results = []
        for block in tool_use_blocks:
            tool_name = block["name"]
            tool_args = dict(block.get("input") or {})

            tool_entry = TOOLS.get(tool_name)
            if tool_entry is None or tool_name in _DISALLOWED_TOOLS:
                # The LLM hallucinated a tool name or asked for something
                # on the denylist -- report it as a normal tool_result
                # error and let the LLM recover, rather than crashing the
                # whole chat turn (see ADR-011 §4).
                result: dict[str, Any] = {
                    "error": "unknown_or_disallowed_tool",
                    "message": f"Tool '{tool_name}' is not available to ai_chat.",
                }
                is_error = True
            else:
                if _SESSION_ARG_NAME in tool_entry["inputSchema"].get("properties", {}):
                    # Pin, ADR-011 §2: never trust a session_id the LLM
                    # supplied itself.
                    tool_args[_SESSION_ARG_NAME] = session_id

                handler = tool_entry["handler"]
                try:
                    result = await handler(runtime, tool_args)
                    is_error = bool(isinstance(result, dict) and result.get("error"))
                except Exception as exc:
                    result = {"error": str(exc) or "An internal error occurred."}
                    is_error = True

            executed_calls.append(
                {
                    "name": tool_name,
                    "arguments": tool_args,
                    "result": result,
                    "is_error": is_error,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return {
        "reply": "Reached the tool-call iteration limit without a final answer.",
        "tool_calls": executed_calls,
        "messages": messages,
        # Structured flag alongside the human-readable reply above, so
        # callers (e.g. cks-studio's useAiChat) can detect this specific,
        # retriable condition without string-matching the reply text.
        "truncated": True,
    }
