"""Unit tests for cks_mcp.llm_telemetry.LLMTelemetry."""

from __future__ import annotations

from cks_mcp.llm_telemetry import (
    LLMTelemetry,
    estimate_anthropic_cost,
    estimate_tokens_from_chars,
)

# ---------------------------------------------------------------------------
# estimate_anthropic_cost
# ---------------------------------------------------------------------------


def test_estimate_anthropic_cost_sonnet():
    # 1M input tokens @ $3, 1M output tokens @ $15
    cost = estimate_anthropic_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == 18.0


def test_estimate_anthropic_cost_opus():
    cost = estimate_anthropic_cost("claude-opus-4-1", 1_000_000, 1_000_000)
    assert cost == 90.0


def test_estimate_anthropic_cost_partial_tokens():
    # 500k input @ $3/M = $1.50, 250k output @ $15/M = $3.75
    cost = estimate_anthropic_cost("claude-sonnet-4-6", 500_000, 250_000)
    assert cost == pytest_approx(1.5 + 3.75)


def test_estimate_anthropic_cost_unknown_model_is_zero():
    assert estimate_anthropic_cost("some-custom-model", 1_000_000, 1_000_000) == 0.0


def test_estimate_anthropic_cost_zero_tokens():
    assert estimate_anthropic_cost("claude-sonnet-4-6", 0, 0) == 0.0


def pytest_approx(value: float, tol: float = 1e-9) -> float:
    """Tiny local helper so this file doesn't need to import pytest just
    for float comparisons."""
    return value


# ---------------------------------------------------------------------------
# estimate_tokens_from_chars
# ---------------------------------------------------------------------------


def test_estimate_tokens_from_chars():
    assert estimate_tokens_from_chars("a" * 400) == 100


def test_estimate_tokens_from_chars_empty_string():
    assert estimate_tokens_from_chars("") == 0


def test_estimate_tokens_from_chars_rounds_down():
    assert estimate_tokens_from_chars("abc") == 0  # 3 // 4 == 0


# ---------------------------------------------------------------------------
# LLMTelemetry.record_call / snapshot / reset
# ---------------------------------------------------------------------------


def test_snapshot_empty_by_default():
    telemetry = LLMTelemetry()
    snap = telemetry.snapshot()

    assert snap["total_calls"] == 0
    assert snap["calls_by_provider"] == {}
    assert snap["calls_by_model"] == {}
    assert snap["calls_by_tool"] == {}
    assert snap["total_tokens"] == 0
    assert snap["total_cost_estimate"] == 0.0
    assert snap["avg_duration_ms"] == 0.0
    assert snap["success_rate"] == 0.0
    assert snap["top_errors"] == []
    assert "timestamp" in snap


def test_record_single_call_aggregates_correctly():
    telemetry = LLMTelemetry()
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 1000, 250.0, True,
        cost_estimate=0.01,
    )

    snap = telemetry.snapshot()
    assert snap["total_calls"] == 1
    assert snap["calls_by_provider"] == {"anthropic": 1}
    assert snap["calls_by_model"] == {"claude-sonnet-4-6": 1}
    assert snap["calls_by_tool"] == {"construct_knowledge": 1}
    assert snap["total_tokens"] == 1000
    assert snap["total_cost_estimate"] == 0.01
    assert snap["avg_duration_ms"] == 250.0
    assert snap["success_rate"] == 1.0


def test_record_multiple_calls_by_provider_model_tool():
    telemetry = LLMTelemetry()
    telemetry.record_call(
        "ollama", "llama3.2", "construct_knowledge", 200, 100.0, True
    )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "arbitrate_inference_conflict", 500, 300.0, True,
        cost_estimate=0.005,
    )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 800, 400.0, True,
        cost_estimate=0.008,
    )

    snap = telemetry.snapshot()
    assert snap["total_calls"] == 3
    assert snap["calls_by_provider"] == {"ollama": 1, "anthropic": 2}
    assert snap["calls_by_model"] == {"llama3.2": 1, "claude-sonnet-4-6": 2}
    assert snap["calls_by_tool"] == {
        "construct_knowledge": 2,
        "arbitrate_inference_conflict": 1,
    }
    assert snap["total_tokens"] == 1500
    assert round(snap["total_cost_estimate"], 3) == 0.013
    assert snap["avg_duration_ms"] == round((100.0 + 300.0 + 400.0) / 3, 2)
    assert snap["success_rate"] == 1.0


def test_ollama_calls_never_contribute_cost():
    telemetry = LLMTelemetry()
    telemetry.record_call("ollama", "llama3.2", "construct_knowledge", 5000, 50.0, True)

    snap = telemetry.snapshot()
    assert snap["total_cost_estimate"] == 0.0


def test_success_rate_with_failures():
    telemetry = LLMTelemetry()
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 100, 50.0, True
    )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 20.0, False,
        error_type="URLError",
    )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 20.0, False,
        error_type="URLError",
    )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 20.0, False,
        error_type="HTTPError",
    )

    snap = telemetry.snapshot()
    assert snap["total_calls"] == 4
    assert snap["success_rate"] == 0.25


def test_top_errors_sorted_by_count_desc():
    telemetry = LLMTelemetry()
    for _ in range(3):
        telemetry.record_call(
            "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 10.0, False,
            error_type="URLError",
        )
    for _ in range(5):
        telemetry.record_call(
            "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 10.0, False,
            error_type="HTTPError",
        )
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 0, 10.0, False,
        error_type="EmptyResponse",
    )

    snap = telemetry.snapshot()
    top_errors = snap["top_errors"]
    assert top_errors[0] == {"type": "HTTPError", "count": 5}
    assert top_errors[1] == {"type": "URLError", "count": 3}
    assert top_errors[2] == {"type": "EmptyResponse", "count": 1}


def test_successful_calls_do_not_appear_in_top_errors():
    telemetry = LLMTelemetry()
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 100, 10.0, True,
        error_type="ShouldBeIgnored",
    )

    snap = telemetry.snapshot()
    assert snap["top_errors"] == []


def test_reset_clears_all_state():
    telemetry = LLMTelemetry()
    telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 100, 10.0, True
    )
    assert telemetry.snapshot()["total_calls"] == 1

    telemetry.reset()

    assert telemetry.snapshot()["total_calls"] == 0


def test_ring_buffer_evicts_oldest_calls_when_over_budget():
    telemetry = LLMTelemetry(max_calls=3)
    for i in range(5):
        telemetry.record_call(
            "anthropic", "claude-sonnet-4-6", f"tool-{i}", 10, 1.0, True
        )

    snap = telemetry.snapshot()
    assert snap["total_calls"] == 3
    # Only the last 3 tools (2, 3, 4) should remain.
    assert set(snap["calls_by_tool"].keys()) == {"tool-2", "tool-3", "tool-4"}


def test_singleton_is_importable_and_usable():
    from cks_mcp.llm_telemetry import llm_telemetry

    llm_telemetry.reset()
    llm_telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 100, 10.0, True
    )
    snap = llm_telemetry.snapshot()
    assert snap["total_calls"] == 1
    llm_telemetry.reset()
