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

_STEP_C = {
    "step_id": "step-c",
    "operator": "inductive",
    "confidence": 0.7,
    "justification": "Supported by several observed instances.",
    "alternatives_considered": ["step-d's premise"],
    "premises": [],
}
_STEP_D = {
    "step_id": "step-d",
    "operator": "heuristic",
    "confidence": 0.4,
    "justification": "Rule of thumb.",
    "alternatives_considered": [],
    "premises": [],
}

_VALID_BATCH_DECISION = json.dumps(
    [
        {
            "conclusion_id": "obj-1",
            "winner_step_id": "step-a",
            "reasoning": "Deductive beats heuristic here.",
            "runner_up_ids": ["step-b"],
            "confidence_in_decision": 0.85,
        },
        {
            "conclusion_id": "obj-2",
            "winner_step_id": "step-c",
            "reasoning": "Inductive with alternatives considered beats bare heuristic.",
            "runner_up_ids": ["step-d"],
            "confidence_in_decision": 0.7,
        },
    ]
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


def _make_batch_runtime(
    steps_by_conclusion: dict[str, list[dict]], *, session_id: str = "s1"
) -> MagicMock:
    """
    Like _make_runtime, but returns a different active_steps list per
    conclusion_id -- batch mode gathers each conclusion_id
    independently, so a single fixed return_value (as _make_runtime
    uses) can't distinguish between them.
    """
    session = MagicMock()
    session.session_id = session_id
    session.knowledge_structure = MagicMock()

    async def _execute(op, _session):
        steps = steps_by_conclusion.get(op.object_id, [])
        return MagicMock(succeeded=True, payload={"active_steps": steps, "superseded_steps": []})

    runtime = MagicMock()
    runtime.get_session = MagicMock(return_value=session)
    runtime.executor.execute = AsyncMock(side_effect=_execute)
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


class TestBatchBasicErrors:
    async def test_both_conclusion_id_and_conclusion_ids_given(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_runtime([_STEP_A, _STEP_B])
        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "conclusion_id": "obj-1", "conclusion_ids": ["obj-2"]},
        )
        assert result.get("error") == "invalid_parameter"

    async def test_winner_id_with_conclusion_ids_is_rejected(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B]})
        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "conclusion_ids": ["obj-1"], "winner_id": "step-a"},
        )
        assert result.get("error") == "invalid_parameter"

    async def test_conclusion_ids_must_be_a_list(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({})
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_ids": "obj-1"}
        )
        assert result.get("error") == "invalid_parameter"

    async def test_conclusion_ids_must_be_non_empty(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({})
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_ids": []}
        )
        assert result.get("error") == "invalid_parameter"

    async def test_conclusion_ids_rejects_duplicates(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B]})
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_ids": ["obj-1", "obj-1"]}
        )
        assert result.get("error") == "invalid_parameter"

    async def test_winners_must_be_an_object(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B]})
        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "conclusion_ids": ["obj-1"], "winners": ["step-a"]},
        )
        assert result.get("error") == "invalid_parameter"

    async def test_batch_session_not_found(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = MagicMock()
        runtime.get_session = MagicMock(return_value=None)
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "missing", "conclusion_ids": ["obj-1"]}
        )
        assert result.get("error") == "session_not_found"


class TestBatchNoDecision:
    async def test_mixed_conflict_and_no_conflict_entries(self):
        """One conclusion has <2 active steps (nothing to arbitrate), the
        other has a genuine unresolved conflict -- both show up in
        'results' with their own shape, and the batch itself succeeds."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A], "obj-2": [_STEP_C, _STEP_D]})
        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_ids": ["obj-1", "obj-2"]}
        )

        assert result["session_id"] == "s1"
        assert "policy" in result and isinstance(result["policy"], str)
        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"]["conflict"] is False
        assert "decision" not in by_id["obj-1"]
        assert by_id["obj-2"]["conflict"] is True
        assert by_id["obj-2"]["active_steps"] == [_STEP_C, _STEP_D]
        assert "decision" not in by_id["obj-2"]

    async def test_one_bad_conclusion_id_does_not_abort_the_batch(self):
        """explain_inference failing for one conclusion_id only shows up
        as that entry's own error -- the rest of the batch still
        resolves normally."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        session = MagicMock()
        session.session_id = "s1"
        session.knowledge_structure = MagicMock()

        async def _execute(op, _session):
            if op.object_id == "bad-id":
                return MagicMock(succeeded=False, error="boom", payload=None)
            return MagicMock(
                succeeded=True,
                payload={"active_steps": [_STEP_A, _STEP_B], "superseded_steps": []},
            )

        runtime = MagicMock()
        runtime.get_session = MagicMock(return_value=session)
        runtime.executor.execute = AsyncMock(side_effect=_execute)

        result = await arbitrate_inference_conflict(
            runtime, {"session_id": "s1", "conclusion_ids": ["bad-id", "obj-1"]}
        )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["bad-id"].get("error") == "internal_error"
        assert by_id["obj-1"]["conflict"] is True
        assert by_id["obj-1"]["active_steps"] == [_STEP_A, _STEP_B]


class TestBatchCallerSuppliedWinners:
    async def test_winners_resolves_the_named_conclusion_only(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        result = await arbitrate_inference_conflict(
            runtime,
            {
                "session_id": "s1",
                "conclusion_ids": ["obj-1", "obj-2"],
                "winners": {"obj-1": "step-a"},
            },
        )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"]["decision_source"] == "caller"
        assert by_id["obj-1"]["decision"]["winner_step_id"] == "step-a"
        # obj-2 has no entry in 'winners' and no auto_resolve -- left undecided.
        assert "decision" not in by_id["obj-2"]

    async def test_invalid_winner_in_winners_only_affects_its_own_entry(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        result = await arbitrate_inference_conflict(
            runtime,
            {
                "session_id": "s1",
                "conclusion_ids": ["obj-1", "obj-2"],
                "winners": {"obj-1": "step-does-not-exist", "obj-2": "step-c"},
            },
        )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"].get("error") == "invalid_parameter"
        assert "decision" not in by_id["obj-1"]
        assert by_id["obj-2"]["decision"]["winner_step_id"] == "step-c"


class TestBatchAutoResolve:
    async def test_combined_call_resolves_every_pending_conclusion(self):
        """Exactly ONE LLM call covers both conclusion_ids -- the entire
        point of batch mode -- not one call per conflict."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
            return_value=_VALID_BATCH_DECISION,
        ) as mock_call:
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "auto_resolve": True,
                },
            )

        mock_call.assert_called_once()
        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"]["decision_source"] == "auto_resolve"
        assert by_id["obj-1"]["decision"]["winner_step_id"] == "step-a"
        assert by_id["obj-2"]["decision_source"] == "auto_resolve"
        assert by_id["obj-2"]["decision"]["winner_step_id"] == "step-c"

    async def test_winners_entries_are_not_sent_to_the_llm(self):
        """A conclusion already resolved via 'winners' isn't part of the
        combined prompt -- only genuinely pending ones are."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        single_decision = json.dumps(
            [
                {
                    "conclusion_id": "obj-2",
                    "winner_step_id": "step-c",
                    "reasoning": "Only one still pending.",
                    "runner_up_ids": ["step-d"],
                    "confidence_in_decision": 0.7,
                }
            ]
        )
        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
            return_value=single_decision,
        ) as mock_call:
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "winners": {"obj-1": "step-a"},
                    "auto_resolve": True,
                },
            )

        mock_call.assert_called_once()
        sent_prompt = mock_call.call_args[0][0]
        assert "obj-2" in sent_prompt
        assert "obj-1" not in sent_prompt
        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"]["decision_source"] == "caller"
        assert by_id["obj-2"]["decision_source"] == "auto_resolve"

    async def test_missing_entry_in_arbiter_response_only_fails_that_item(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        partial_decision = json.dumps(
            [
                {
                    "conclusion_id": "obj-1",
                    "winner_step_id": "step-a",
                    "reasoning": "ok",
                    "runner_up_ids": ["step-b"],
                    "confidence_in_decision": 0.85,
                }
            ]
        )
        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
            return_value=partial_decision,
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "auto_resolve": True,
                },
            )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"]["decision_source"] == "auto_resolve"
        assert by_id["obj-2"].get("error") == "invalid_arbiter_decision"

    async def test_llm_output_not_json_array_fails_all_pending_items(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
            return_value="not json at all",
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "auto_resolve": True,
                },
            )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"].get("error") == "llm_output_parse_error"
        assert by_id["obj-2"].get("error") == "llm_output_parse_error"

    async def test_llm_call_raises_fails_all_pending_items_but_not_the_batch(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
            side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set."),
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "auto_resolve": True,
                },
            )

        by_id = {r["conclusion_id"]: r for r in result["results"]}
        assert by_id["obj-1"].get("error") == "internal_error"
        assert by_id["obj-2"].get("error") == "internal_error"


class TestBatchCommit:
    async def test_commit_combines_every_decision_into_one_evolve_call(self):
        """winners resolves one conclusion, auto_resolve resolves the
        other -- commit still applies both in a single evolve_knowledge
        call, not one per conclusion_id."""
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        single_decision = json.dumps(
            [
                {
                    "conclusion_id": "obj-2",
                    "winner_step_id": "step-c",
                    "reasoning": "ok",
                    "runner_up_ids": ["step-d"],
                    "confidence_in_decision": 0.7,
                }
            ]
        )
        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B], "obj-2": [_STEP_C, _STEP_D]})
        fake_evolve_result = {"evolved": True, "version_id": "v2"}
        with (
            patch(
                "cks_mcp.tools.arbitrate_inference_conflict.handler._call_anthropic_batch",
                return_value=single_decision,
            ),
            patch(
                "cks_mcp.tools.arbitrate_inference_conflict.handler.evolve_knowledge",
                AsyncMock(return_value=fake_evolve_result),
            ) as mock_evolve,
        ):
            result = await arbitrate_inference_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "conclusion_ids": ["obj-1", "obj-2"],
                    "winners": {"obj-1": "step-a"},
                    "auto_resolve": True,
                    "commit": True,
                },
            )

        assert result["commit_result"] == fake_evolve_result
        mock_evolve.assert_called_once()
        call_kwargs = mock_evolve.call_args[0][1]
        assert call_kwargs["session_id"] == "s1"
        ops = call_kwargs["operations"]
        assert {"type": "resolve_inference_conflict", "conclusion_id": "obj-1", "winner_id": "step-a"} in ops
        assert {"type": "resolve_inference_conflict", "conclusion_id": "obj-2", "winner_id": "step-c"} in ops
        assert len(ops) == 2

    async def test_commit_without_any_decision_errors(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({"obj-1": [_STEP_A, _STEP_B]})
        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "conclusion_ids": ["obj-1"], "commit": True},
        )
        assert result.get("error") == "missing_decision"
        # Still a full, inspectable batch response, not just the error.
        assert "results" in result


class TestStalePremiseResolution:
    async def test_single_stale_premise_rewrite(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        # step-a supersedes step-old, and step-b cites step-old as a premise
        runtime = _make_batch_runtime({})
        session = runtime.get_session.return_value
        structure = MagicMock()
        session.knowledge_structure = structure

        def _get(oid):
            if oid == "step-b":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"premises": ["step-old"]})
            if oid == "step-old":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"superseded_by": "step-a"})
            return None
        structure.get.side_effect = _get

        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "stale_premise_ids": ["step-b"]},
        )
        assert result["results"][0]["resolved"] is True
        assert result["results"][0]["fixes"] == {"step-old": "step-a"}

    async def test_stale_premise_batch(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({})
        session = runtime.get_session.return_value
        structure = MagicMock()
        session.knowledge_structure = structure

        def _get(oid):
            if oid == "step-x":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"premises": ["stale-1"]})
            if oid == "step-y":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"premises": ["stale-2"]})
            if oid == "stale-1":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"superseded_by": "live-1"})
            if oid == "stale-2":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"superseded_by": "live-2"})
            return None
        structure.get.side_effect = _get

        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "stale_premise_ids": ["step-x", "step-y"]},
        )
        assert len(result["results"]) == 2
        assert result["results"][0]["fixes"] == {"stale-1": "live-1"}
        assert result["results"][1]["fixes"] == {"stale-2": "live-2"}

    async def test_stale_premise_commit(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({})
        session = runtime.get_session.return_value
        structure = MagicMock()
        session.knowledge_structure = structure
        def _get(oid):
            if oid == "step-x":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"premises": ["stale-1"]})
            if oid == "stale-1":
                return MagicMock(identity=MagicMock(type="InferenceStep"), structure={"superseded_by": "live-1"})
            return None
        structure.get.side_effect = _get

        fake_evolve = {"evolved": True, "version_id": "v2"}
        with patch(
            "cks_mcp.tools.arbitrate_inference_conflict.handler.evolve_knowledge",
            AsyncMock(return_value=fake_evolve),
        ) as mock_evolve:
            result = await arbitrate_inference_conflict(
                runtime,
                {"session_id": "s1", "stale_premise_ids": ["step-x"], "commit": True},
            )
        assert result["commit_result"] == fake_evolve
        mock_evolve.assert_called_once()

    async def test_stale_premise_rejects_invalid_step(self):
        from cks_mcp.tools.arbitrate_inference_conflict.handler import (
            arbitrate_inference_conflict,
        )

        runtime = _make_batch_runtime({})
        session = runtime.get_session.return_value
        session.knowledge_structure.get.return_value = None

        result = await arbitrate_inference_conflict(
            runtime,
            {"session_id": "s1", "stale_premise_ids": ["nonexistent"]},
        )
        assert "error" in result["results"][0]