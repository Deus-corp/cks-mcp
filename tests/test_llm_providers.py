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