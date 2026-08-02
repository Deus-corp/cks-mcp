"""Unit tests for the arbitrate_inference_conflict MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

_STEP_A = {
    "step_id": "step-a",
    "operator": "deductive",
    "confidence": 0.9,
    "justification": "Derived directly from axioms X and Y.",
    "alternatives_considered": ["step-b's premise"],
    "premises": [],
}
_STEP_B = {
    "step_id": "step-b",
    "operator": "heuristic",
    "confidence": 0.6,
    "justification": "Seems plausible.",
    "alternatives_considered": [],
    "premises": [],
}

_VALID_DECISION = json.dumps(
    {
        "winner_step_id": "step-a",
        "reasoning": "Deductive with a specific justification beats an unsupported heuristic.",
        "runner_up_ids": ["step-b"],
        "confidence_in_decision": 0.85,
    }
)


def _make_runtime(active_steps: list[dict], *, session_id: str = "s1") -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.knowledge_structure = MagicMock()

    runtime = MagicMock()
    runtime.get_session = MagicMock(return_value=session)
    runtime.executor.execute = AsyncMock(
        return_value=MagicMock(
            succeeded=True,
            payload={"active_steps": active_steps, "superseded_steps": []},
        )
    )
    return runtime


class TestNoConflict:
    async def test_zero_active_steps(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([])
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_id": "obj-1"}
        )
        assert result["conflict"] is False
        assert result["active_steps"] == []

    async def test_single_active_step(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A])
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_id": "obj-1"}
        )
        assert result["conflict"] is False
        assert "decision" not in result


class TestBasicErrors:
    async def test_missing_conclusion_id(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(runtime, {"session_id": "s1"})
        assert result.get("error") == "missing_parameter"

    async def test_session_not_found(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = MagicMock()
        runtime.get_session = MagicMock(return_value=None)
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "missing", "conclusion_id": "obj-1"}
        )
        assert result.get("error") == "session_not_found"

    async def test_explain_inference_failure_surfaces_internal_error(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        runtime.executor.execute = AsyncMock(
            return_value=MagicMock(succeeded=False, error="boom", payload=None)
        )
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_id": "obj-1"}
        )
        assert result.get("error") == "internal_error"


class TestConflictNoDecision:
    async def test_returns_active_steps_and_policy_without_deciding(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_id": "obj-1"}
        )
        assert result["conflict"] is True
        assert result["active_steps"] == [_STEP_A, _STEP_B]
        assert "policy" in result and isinstance(result["policy"], str)
        assert "decision" not in result


class TestCallerSuppliedWinner:
    async def test_valid_winner_id(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(
            runtime,
            {
                "session_id": "s1",
                "conclusion_id": "obj-1",
                "winner_id": "step-a",
                "reasoning": "I already checked the premises myself.",
            },
        )
        assert result["decision_source"] == "caller"
        assert result["decision"]["winner_step_id"] == "step-a"
        assert result["decision"]["runner_up_ids"] == ["step-b"]
        assert result["decision"]["reasoning"] == "I already checked the premises myself."

    async def test_invalid_winner_id(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "conclusion_id": "obj-1", "winner_id": "step-nonexistent"},
        )
        assert result.get("error") == "invalid_parameter"


class TestAutoResolve:
    async def test_success(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic",
            return_value=_VALID_DECISION,
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {"session_id": "s1", "conclusion_id": "obj-1", "auto_resolve": True},
            )
        assert result["decision_source"] == "auto_resolve"
        assert result["decision"]["winner_step_id"] == "step-a"
        assert result["decision"]["confidence_in_decision"] == 0.85
        assert "model_used" in result["decision"]

    async def test_winner_id_takes_priority_over_auto_resolve(self):
        """No LLM call at all when 'winner_id' is already given."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic"
        ) as mock_call:
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_id": "obj-1",
                    "winner_id": "step-b",
                    "auto_resolve": True,
                },
            )
        mock_call.assert_not_called()
        assert result["decision_source"] == "caller"
        assert result["decision"]["winner_step_id"] == "step-b"

    async def test_llm_output_not_json(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic",
            return_value="I refuse to output JSON today.",
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {"session_id": "s1", "conclusion_id": "obj-1", "auto_resolve": True},
            )
        assert result.get("error") == "llm_output_parse_error"

    async def test_llm_chooses_unknown_winner(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        bad_decision = json.dumps(
            {
                "winner_step_id": "step-does-not-exist",
                "reasoning": "oops",
                "runner_up_ids": [],
                "confidence_in_decision": 0.5,
            }
        )
        runtime = _make_runtime([_STEP_A, _STEP_B])
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic",
            return_value=bad_decision,
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {"session_id": "s1", "conclusion_id": "obj-1", "auto_resolve": True},
            )
        assert result.get("error") == "invalid_arbiter_decision"

    async def test_llm_call_raises(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic",
            side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set."),
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {"session_id": "s1", "conclusion_id": "obj-1", "auto_resolve": True},
            )
        assert result.get("error") == "internal_error"


class TestCommit:
    async def test_commit_without_decision_errors(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_id": "obj-1", "commit": True}
        )
        assert result.get("error") == "missing_decision"

    async def test_commit_with_caller_winner_calls_evolve_knowledge(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        fake_evolve_result = {"evolved": True, "version_id": "v2"}
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler.evolve_knowledge",
            AsyncMock(return_value=fake_evolve_result),
        ) as mock_evolve:
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_id": "obj-1",
                    "winner_id": "step-a",
                    "commit": True,
                },
            )
        assert result["commit_result"] == fake_evolve_result
        called_args = mock_evolve.call_args[0]
        assert called_args[0] is runtime
        call_kwargs = called_args[1]
        assert call_kwargs["session_id"] == "s1"
        assert call_kwargs["operations"] == [
            {
                "type": "resolve_inference_conflict",
                "conclusion_id": "obj-1",
                "winner_id": "step-a",
            }
        ]
        assert "inference_confidence_conflict" in call_kwargs["extensions"]
