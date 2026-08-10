"""
Direct unit tests for ``cks_mcp.llm_providers``.

This module is the shared, low-level HTTP layer used by both
``construct_knowledge`` and ``ingest_document``'s ``use_llm`` mode.
Before this file, no test exercised it directly: every existing test
mocks it away at a higher layer (``handler._call_ollama``,
``handler._call_anthropic``, or ``handler._build_llm_structure``
entirely), so the actual request-building / response-parsing / error-
handling code here had zero coverage.
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from cks_mcp import llm_providers
from cks_mcp.llm_telemetry import llm_telemetry


@pytest.fixture(autouse=True)
def _reset_llm_telemetry():
    llm_telemetry.reset()
    yield
    llm_telemetry.reset()

# ---------------------------------------------------------------------------
# ollama_host / ollama_available
# ---------------------------------------------------------------------------


def test_ollama_host_default():
    with patch.dict("os.environ", {}, clear=True):
        assert llm_providers.ollama_host() == "http://localhost:11434"


def test_ollama_host_env_override_strips_trailing_slash():
    with patch.dict("os.environ", {"CKS_OLLAMA_HOST": "http://example.com:1234/"}):
        assert llm_providers.ollama_host() == "http://example.com:1234"


def test_ollama_available_true_on_200():
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert llm_providers.ollama_available("http://localhost:11434") is True


def test_ollama_available_false_on_unreachable():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert llm_providers.ollama_available("http://localhost:11434") is False


def test_ollama_available_false_on_os_error():
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert llm_providers.ollama_available("http://localhost:11434") is False


def test_ollama_available_never_raises_on_unexpected_status():
    fake_resp = MagicMock()
    fake_resp.status = 500
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert llm_providers.ollama_available("http://localhost:11434") is False


# ---------------------------------------------------------------------------
# call_ollama
# ---------------------------------------------------------------------------


def _fake_urlopen_returning(body: dict):
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(body).encode()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    return fake_resp


def test_call_ollama_success():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"response": "hello"})):
        result = llm_providers.call_ollama(
            "prompt", system_prompt="sys", model="llama3.2", max_tokens=100
        )
    assert result == "hello"


def test_call_ollama_empty_response_raises():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"response": ""})), \
         pytest.raises(RuntimeError, match="no text"):
        llm_providers.call_ollama("prompt", system_prompt="sys", model="llama3.2", max_tokens=100)


def test_call_ollama_http_error_mentions_model_pull():
    err = urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(b"model not found"),
    )
    with patch("urllib.request.urlopen", side_effect=err), \
         pytest.raises(RuntimeError, match="ollama pull llama3.2"):
        llm_providers.call_ollama("prompt", system_prompt="sys", model="llama3.2", max_tokens=100)


def test_call_ollama_url_error_mentions_ollama_serve():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")), \
         pytest.raises(RuntimeError, match="ollama serve"):
        llm_providers.call_ollama("prompt", system_prompt="sys", model="llama3.2", max_tokens=100)


# ---------------------------------------------------------------------------
# call_anthropic
# ---------------------------------------------------------------------------


def test_call_anthropic_missing_api_key_raises():
    with patch.dict("os.environ", {}, clear=True), \
         pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )


def test_call_anthropic_success():
    body = {"content": [{"type": "text", "text": "hello from claude"}]}
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )
    assert result == "hello from claude"


def test_call_anthropic_joins_multiple_text_blocks():
    body = {"content": [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]}
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )
    assert result == "part1\npart2"


def test_call_anthropic_no_content_blocks_raises():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"content": []})), \
         pytest.raises(RuntimeError, match="no content blocks"):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )


def test_call_anthropic_no_text_blocks_raises():
    body = {"content": [{"type": "tool_use"}], "stop_reason": "tool_use"}
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)), \
         pytest.raises(RuntimeError, match="no text blocks"):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )


def test_call_anthropic_http_error_includes_status_code():
    err = urllib.error.HTTPError(
        url="https://api.anthropic.com/v1/messages",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b"invalid x-api-key"),
    )
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", side_effect=err), \
         pytest.raises(RuntimeError, match="HTTP 401"):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )


def test_call_anthropic_url_error_raises():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns failure")), \
         pytest.raises(RuntimeError, match="Network error"):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


def test_extract_json_raw_object():
    raw = '{"objects": []}'
    assert llm_providers.extract_json(raw) == raw


def test_extract_json_strips_markdown_fence():
    raw = '```json\n{"objects": []}\n```'
    assert llm_providers.extract_json(raw) == '{"objects": []}'


def test_extract_json_ignores_braces_inside_strings():
    raw = 'noise before {"a": "value with } brace", "b": 2} noise after'
    assert llm_providers.extract_json(raw) == '{"a": "value with } brace", "b": 2}'


def test_extract_json_handles_nested_objects():
    raw = 'prefix {"outer": {"inner": {"deep": 1}}} suffix'
    assert llm_providers.extract_json(raw) == '{"outer": {"inner": {"deep": 1}}}'


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError, match="No JSON object found"):
        llm_providers.extract_json("just plain text, no braces here")


def test_extract_json_unbalanced_braces_raises():
    with pytest.raises(ValueError, match="Unbalanced braces"):
        llm_providers.extract_json('{"a": 1, "b": {"c": 2}')


def test_extract_json_rejects_truncated_output_even_when_it_starts_with_brace():
    truncated = '{"objects": [{"identity": {"id": "a", "type": "T", "name": "n"}'
    with pytest.raises(ValueError, match="Unbalanced braces"):
        llm_providers.extract_json(truncated)


def test_extract_json_trims_trailing_commentary_even_when_it_starts_with_brace():
    raw = '{"objects": []}\n\nHope this helps! Let me know if you need anything else.'
    assert llm_providers.extract_json(raw) == '{"objects": []}'


# ---------------------------------------------------------------------------
# tool_name -> llm_telemetry integration
# ---------------------------------------------------------------------------


def test_call_ollama_without_tool_name_does_not_record():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"response": "hello"})):
        llm_providers.call_ollama("prompt", system_prompt="sys", model="llama3.2", max_tokens=100)

    assert llm_telemetry.snapshot()["total_calls"] == 0


def test_call_ollama_with_tool_name_records_success():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"response": "hello"})):
        llm_providers.call_ollama(
            "prompt",
            system_prompt="sys",
            model="llama3.2",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["calls_by_provider"] == {"ollama": 1}
    assert snap["calls_by_model"] == {"llama3.2": 1}
    assert snap["calls_by_tool"] == {"construct_knowledge": 1}
    assert snap["success_rate"] == 1.0
    # Ollama is always free.
    assert snap["total_cost_estimate"] == 0.0
    # chars/4 estimate over system_prompt + prompt + response ("sys" + "prompt" + "hello" = 14 chars)
    assert snap["total_tokens"] == len("sys" + "prompt" + "hello") // 4


def test_call_ollama_with_tool_name_records_failure_on_http_error():
    err = urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(b"model not found"),
    )
    with patch("urllib.request.urlopen", side_effect=err), pytest.raises(RuntimeError):
        llm_providers.call_ollama(
            "prompt",
            system_prompt="sys",
            model="llama3.2",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 0.0
    assert snap["top_errors"] == [{"type": "HTTPError", "count": 1}]


def test_call_ollama_with_tool_name_records_failure_on_empty_response():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"response": ""})), \
         pytest.raises(RuntimeError, match="no text"):
        llm_providers.call_ollama(
            "prompt",
            system_prompt="sys",
            model="llama3.2",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 0.0
    assert snap["top_errors"] == [{"type": "EmptyResponse", "count": 1}]


def test_call_anthropic_without_tool_name_does_not_record():
    body = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        llm_providers.call_anthropic(
            "prompt", system_prompt="sys", model="claude-sonnet-4-6", max_tokens=100
        )

    assert llm_telemetry.snapshot()["total_calls"] == 0


def test_call_anthropic_with_tool_name_records_success_using_real_usage():
    body = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 1000, "output_tokens": 500},
    }
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        llm_providers.call_anthropic(
            "prompt",
            system_prompt="sys",
            model="claude-sonnet-4-6",
            max_tokens=100,
            tool_name="arbitrate_inference_conflict",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["calls_by_provider"] == {"anthropic": 1}
    assert snap["calls_by_tool"] == {"arbitrate_inference_conflict": 1}
    assert snap["total_tokens"] == 1500
    # 1000 in @ $3/M + 500 out @ $15/M = 0.003 + 0.0075 = 0.0105
    assert snap["total_cost_estimate"] == pytest.approx(0.0105)
    assert snap["success_rate"] == 1.0


def test_call_anthropic_with_tool_name_records_failure_on_url_error_with_zero_tokens():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns failure")), \
         pytest.raises(RuntimeError):
        llm_providers.call_anthropic(
            "prompt",
            system_prompt="sys",
            model="claude-sonnet-4-6",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 0.0
    assert snap["total_tokens"] == 0
    assert snap["total_cost_estimate"] == 0.0
    assert snap["top_errors"] == [{"type": "URLError", "count": 1}]


def test_call_anthropic_with_tool_name_records_failure_on_no_text_blocks_still_bills_usage():
    body = {
        "content": [{"type": "tool_use"}],
        "usage": {"input_tokens": 200, "output_tokens": 0},
        "stop_reason": "tool_use",
    }
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)), \
         pytest.raises(RuntimeError, match="no text blocks"):
        llm_providers.call_anthropic(
            "prompt",
            system_prompt="sys",
            model="claude-sonnet-4-6",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 0.0
    # Usage was still billed even though the response had no usable text.
    assert snap["total_tokens"] == 200
    assert snap["total_cost_estimate"] == pytest.approx((200 / 1_000_000) * 3.0)
    assert snap["top_errors"] == [{"type": "NoTextBlocks", "count": 1}]


def test_call_anthropic_missing_api_key_does_not_record_since_no_request_was_made():
    with patch.dict("os.environ", {}, clear=True), \
         pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm_providers.call_anthropic(
            "prompt",
            system_prompt="sys",
            model="claude-sonnet-4-6",
            max_tokens=100,
            tool_name="construct_knowledge",
        )

    # Fails before the HTTP request is even built -- nothing to record.
    assert llm_telemetry.snapshot()["total_calls"] == 0

# ---------------------------------------------------------------------------
# call_ollama_with_tools (cks-mcp ADR-011 §6)
# ---------------------------------------------------------------------------

_TOOL_SPECS = [
    {
        "name": "query_subgraph",
        "description": "Read the graph.",
        "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}}},
    }
]


def test_call_ollama_with_tools_text_only_reply():
    body = {"message": {"role": "assistant", "content": "hello there"}}
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=_TOOL_SPECS,
            model="llama3.1",
        )

    assert result == {"content": [{"type": "text", "text": "hello there"}]}


def test_call_ollama_with_tools_tool_use_reply_matches_anthropic_shape():
    body = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc",
                    "function": {
                        "name": "query_subgraph",
                        "arguments": {"session_id": "s1"},
                    },
                }
            ],
        }
    }
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "read the graph"}],
            tools=_TOOL_SPECS,
            model="llama3.1",
        )

    assert result["content"] == [
        {
            "type": "tool_use",
            "id": "call_abc",
            "name": "query_subgraph",
            "input": {"session_id": "s1"},
        }
    ]


def test_call_ollama_with_tools_parses_stringified_arguments():
    body = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "query_subgraph", "arguments": '{"session_id": "s1"}'}}
            ],
        }
    }
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS, model="llama3.1"
        )

    assert result["content"][0]["input"] == {"session_id": "s1"}


def test_call_ollama_with_tools_translates_tool_result_messages():
    """A prior tool_result message (Anthropic shape) must become a
    dedicated 'tool' role message Ollama's /api/chat understands, not
    be silently dropped."""
    captured_payload = {}

    def _capture_and_respond(req, timeout=None):
        captured_payload.update(json.loads(req.data.decode()))
        return _fake_urlopen_returning({"message": {"role": "assistant", "content": "ok"}})

    messages = [
        {"role": "user", "content": "read the graph"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call_1", "name": "query_subgraph", "input": {}}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": '{"objects": []}'}
            ],
        },
    ]

    with patch("urllib.request.urlopen", side_effect=_capture_and_respond):
        llm_providers.call_ollama_with_tools(messages=messages, tools=_TOOL_SPECS, model="llama3.1")

    roles = [m["role"] for m in captured_payload["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert captured_payload["messages"][1]["tool_calls"][0]["function"]["name"] == "query_subgraph"
    assert captured_payload["messages"][2]["content"] == '{"objects": []}'


def test_call_ollama_with_tools_no_message_field_raises():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning({"done": True})), \
         pytest.raises(RuntimeError, match="no 'message' field"):
        llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS, model="llama3.1"
        )


def test_call_ollama_with_tools_unreachable_raises_actionable_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")), \
         pytest.raises(RuntimeError, match="Could not reach Ollama"):
        llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS, model="llama3.1"
        )


def test_call_ollama_with_tools_records_telemetry_on_success():
    body = {"message": {"role": "assistant", "content": "hello"}}
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        llm_providers.call_ollama_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=_TOOL_SPECS,
            model="llama3.1",
            tool_name="ai_chat",
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 1.0


# ---------------------------------------------------------------------------
# call_openai_compatible_with_tools
# ---------------------------------------------------------------------------


def test_call_openai_compatible_missing_api_key_raises():
    with patch.dict("os.environ", {}, clear=True), \
         pytest.raises(RuntimeError, match="CKS_OPENAI_API_KEY"):
        llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS
        )


def test_call_openai_compatible_success_text_response():
    body = {
        "choices": [
            {"message": {"role": "assistant", "content": "hello from gpt"}}
        ],
        "usage": {"total_tokens": 42},
    }
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS
        )
    assert result == {"content": [{"type": "text", "text": "hello from gpt"}]}


def test_call_openai_compatible_success_tool_use_response():
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "search_semantic",
                                "arguments": json.dumps({"query": "foo"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"total_tokens": 10},
    }
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS
        )
    assert result["content"] == [
        {
            "type": "tool_use",
            "id": "call_123",
            "name": "search_semantic",
            "input": {"query": "foo"},
        }
    ]


def test_call_openai_compatible_http_error_includes_base_url():
    err = urllib.error.HTTPError(
        url="https://api.openai.com/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b"invalid api key"),
    )
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", side_effect=err), \
         pytest.raises(RuntimeError, match="HTTP 401"):
        llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS
        )


def test_call_openai_compatible_url_error_mentions_base_url():
    with patch.dict(
        "os.environ",
        {"CKS_OPENAI_API_KEY": "fake-key", "CKS_OPENAI_BASE_URL": "http://localhost:1234/v1"},
    ), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")), \
         pytest.raises(RuntimeError, match="http://localhost:1234/v1"):
        llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}], tools=_TOOL_SPECS
        )


def test_call_openai_compatible_uses_custom_base_url_and_model():
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return _fake_urlopen_returning(body)

    with patch.dict(
        "os.environ",
        {
            "CKS_OPENAI_API_KEY": "fake-key",
            "CKS_OPENAI_BASE_URL": "https://api.groq.com/openai/v1",
            "CKS_OPENAI_MODEL": "llama-3.3-70b",
        },
    ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        llm_providers.call_openai_compatible_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=_TOOL_SPECS,
            model=os.environ.get("CKS_OPENAI_MODEL"),
        )

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["payload"]["model"] == "llama-3.3-70b"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# call_openai_compatible_single_shot
# ---------------------------------------------------------------------------


def test_call_openai_compatible_single_shot_missing_api_key_raises():
    with patch.dict("os.environ", {}, clear=True), \
         pytest.raises(RuntimeError, match="CKS_OPENAI_API_KEY"):
        llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100
        )


def test_call_openai_compatible_single_shot_success():
    body = {
        "choices": [{"message": {"role": "assistant", "content": "hello from gpt"}}],
        "usage": {"total_tokens": 12},
    }
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        result = llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100
        )
    assert result == "hello from gpt"


def test_call_openai_compatible_single_shot_empty_response_raises():
    body = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)), \
         pytest.raises(RuntimeError, match="no text"):
        llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100
        )


def test_call_openai_compatible_single_shot_http_error_includes_status_code():
    err = urllib.error.HTTPError(
        url="https://api.openai.com/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b"invalid api key"),
    )
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", side_effect=err), \
         pytest.raises(RuntimeError, match="HTTP 401"):
        llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100
        )


def test_call_openai_compatible_single_shot_url_error_mentions_base_url():
    with patch.dict(
        "os.environ",
        {"CKS_OPENAI_API_KEY": "fake-key", "CKS_OPENAI_BASE_URL": "http://localhost:1234/v1"},
    ), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")), \
         pytest.raises(RuntimeError, match="http://localhost:1234/v1"):
        llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100
        )


def test_call_openai_compatible_single_shot_records_telemetry_on_success():
    body = {
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": {"total_tokens": 7},
    }
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "fake-key"}), \
         patch("urllib.request.urlopen", return_value=_fake_urlopen_returning(body)):
        llm_providers.call_openai_compatible_single_shot(
            "prompt", system_prompt="sys", model="gpt-4o", max_tokens=100, tool_name="construct_knowledge"
        )

    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["success_rate"] == 1.0
