"""
arbitrate_inference_conflict: resolve an InferenceConfidenceConflict
(ADR-001) -- two or more active InferenceSteps that conclude the same
object but disagree -- by applying an explicit "whose conclusion is
stronger" policy.

This is deliberately *not* a generic critic wired through a
configurable prompt: the policy in ``_ARBITER_POLICY`` below encodes
one specific way of weighing operator strength, confidence
calibration, premise health, and alternatives-considered against each
other, written for how this arbiter's one currently-supported
interactive client (Claude Desktop, per this project's own test
matrix) actually reasons about competing evidence. A different
policy is a different tool, not a parameter of this one.

Three ways to reach and apply a decision (see schema.py's
description for the caller-facing version of this):

1. Interactive, no extra LLM call: this MCP server's calling client
   is typically itself an LLM already looking at conversation
   context. Called with no 'winner_id' and no 'auto_resolve', this
   tool returns the competing 'active_steps' (ranked by entrenchment,
   same shape explain_knowledge already returns for an object_id) and
   the 'policy' text below, so that client can weigh them itself --
   the same reasoning ``_ARBITER_POLICY`` describes, just performed
   in-context instead of via a second API round-trip -- and call this
   tool again with 'winner_id' set to its own decision. (Mirrors
   construct_knowledge's own "skip this tool, the caller can already
   do the reasoning" escape hatch -- MCP's sampling feature, which
   would otherwise let a server ask its *connected client's* model to
   do this, was deprecated in the 2026-07-28 protocol revision.)

2. Unattended (auto_resolve=True): for a background Critic agent with
   no interactive client driving it -- e.g. reacting to
   list_gossip_conflicts on its own schedule -- this tool makes its
   own LLM call via the same 'auto' | 'ollama' | 'anthropic' provider
   dispatch construct_knowledge already uses (CKS_LLM_* env vars),
   applying _ARBITER_POLICY, and returns its decision in the same
   shape a caller-supplied 'winner_id' would have produced.

3. Bypass entirely: a caller can always ignore this tool's decision
   machinery and apply evolve_knowledge's 'resolve_inference_conflict'
   operation directly once it knows a winner_id.

All three converge on the same commit path: pass 'commit': true (with
either 'winner_id' or 'auto_resolve') to have this tool apply the
winning step via evolve_knowledge and persist a new version, instead
of only returning the decision for the caller to apply itself.

Environment variables (auto_resolve only; same names/semantics as
construct_knowledge's, see llm_providers.py):
    CKS_LLM_PROVIDER      -- "auto" (default) | "ollama" | "anthropic".
    ANTHROPIC_API_KEY     -- required only for the "anthropic" provider.
    CKS_ARBITER_MODEL     -- model override (falls back to CKS_LLM_MODEL,
                              then "claude-sonnet-4-6").
    CKS_OLLAMA_MODEL      -- model override for the "ollama" provider
                              (default: llama3.2).
    CKS_OLLAMA_HOST       -- Ollama server URL (default: http://localhost:11434).
    CKS_ARBITER_MAX_TOKENS -- optional override (default: 1024 -- the
                              decision is a small JSON object, not prose).
"""

from __future__ import annotations

import json
import os
from typing import Any

from cks_runtime.operations.operation_types import ExplainInferenceOperation
from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.errors import (
    internal_error,
    invalid_parameter,
    missing_parameter,
    session_not_found,
)
from cks_mcp.tools.evolve.handler import evolve_knowledge

# ---------------------------------------------------------------------------
# The arbitration policy
# ---------------------------------------------------------------------------
#
# Returned verbatim as the response's "policy" field (path 1 above) and
# embedded in the LLM system prompt (path 2) -- one statement of the
# criteria, not two copies that could drift apart.

_ARBITER_POLICY = """\
You are deciding which of several competing, currently-active InferenceSteps \
should remain the accepted conclusion for a given object, and which should be \
superseded. Weigh the candidates against each other using all of the following; \
none of them alone is decisive:

1. Operator strength is a prior, not a verdict. Deductive outranks inductive, \
which outranks abductive, which outranks heuristic -- but a well-supported \
abductive step with a specific, checkable justification beats a deductive step \
whose justification is generic or hides an unstated premise. Don't let the \
operator label substitute for reading the justification.

2. Confidence must be earned by the justification, not just asserted. A high \
confidence score paired with a vague justification ("this seems likely", \
"probably true") is weaker than a lower stated confidence backed by a concrete, \
specific argument. Treat a mismatch between the confidence number and the \
actual argument given as a reason to trust that step less, not more.

3. Premise health matters. Look at each step's premise nodes: a premise that is \
itself truncated by a cycle, already superseded, or missing entirely leaves the \
step arguing from a belief the system has already moved past (or never had) -- \
discount it accordingly, even if its own confidence field looks high.

4. Alternatives considered is evidence of epistemic work. A step whose \
alternatives_considered names and rules out real competing explanations has \
done more to earn its conclusion than one that lists none -- prefer it, all \
else equal.

5. Prefer justifications that are specific and falsifiable -- citing a \
mechanism, a premise chain, or a concrete fact -- over ones that are circular, \
merely restate the conclusion, or could not in principle be checked.

6. If, after weighing 1-5, the candidates are genuinely still tied, defer to \
the order they were given to you in (already ranked by entrenchment: \
confidence descending, then declared structure order) rather than inventing a \
new tiebreak.

Be honest in your reasoning: if the decision is close, say so plainly instead \
of writing a more decisive-sounding rationale than the evidence supports -- and \
reflect that in a lower confidence_in_decision, not by hiding the ambiguity. \
You must still name exactly one winner; "too close to call" is not a valid \
winner_step_id.

Respond with ONLY a single JSON object, no markdown fences and no commentary \
before or after it, of exactly this shape:
{
  "winner_step_id": "<step_id of the InferenceStep that should remain active>",
  "reasoning": "<2-4 sentences citing which of the criteria above decided it>",
  "runner_up_ids": ["<step_id>", "..."],
  "confidence_in_decision": <0.0-1.0, your own confidence in this call, distinct \
from any confidence field on the steps themselves>
}
"""

_ARBITER_SYSTEM_PROMPT = _ARBITER_POLICY


# ---------------------------------------------------------------------------
# LLM call -- thin wrappers around cks_mcp.llm_providers, binding in this
# tool's own _ARBITER_SYSTEM_PROMPT. Same shape as construct_knowledge's
# _call_ollama/_call_anthropic/_call_llm so provider-selection behavior
# (and how tests patch it) stays consistent across tools that call an LLM.
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_ollama(
        prompt, system_prompt=_ARBITER_SYSTEM_PROMPT, model=model, max_tokens=max_tokens
    )


def _call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_anthropic(
        prompt, system_prompt=_ARBITER_SYSTEM_PROMPT, model=model, max_tokens=max_tokens
    )


def _default_model() -> str:
    return os.environ.get("CKS_ARBITER_MODEL") or os.environ.get(
        "CKS_LLM_MODEL", "claude-sonnet-4-6"
    )


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> tuple[str, str]:
    """
    Route the arbitration prompt to whichever LLM provider is configured
    or available. Returns (raw_text, model_used). Raises RuntimeError
    with a message listing every option -- including the non-LLM escape
    hatch of supplying 'winner_id' directly -- when no provider works.
    """
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, m, max_tokens), m

    if provider == "anthropic":
        m = model or _default_model()
        return _call_anthropic(prompt, m, max_tokens), m

    if provider != "auto":
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', or 'anthropic'."
        )

    if llm_providers.ollama_available():
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, m, max_tokens), m

    m = model or _default_model()
    try:
        return _call_anthropic(prompt, m, max_tokens), m
    except RuntimeError as exc:
        if "ANTHROPIC_API_KEY" not in str(exc):
            raise
        raise RuntimeError(
            "No LLM provider available for arbitrate_inference_conflict's "
            "auto_resolve. Options: (1) run a local model -- `ollama serve` "
            "+ `ollama pull llama3.2` -- no API key needed; (2) set "
            "ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; (3) skip "
            "auto_resolve entirely -- read this tool's 'active_steps' and "
            "'policy' yourself (this MCP server is typically already being "
            "driven by an LLM client) and call it again with 'winner_id' "
            "set to your own decision."
        ) from exc


def _build_arbiter_prompt(conclusion_id: str, active_steps: list[dict[str, Any]]) -> str:
    return (
        f"Conclusion under dispute: object_id '{conclusion_id}'.\n\n"
        f"{len(active_steps)} active InferenceSteps currently conclude it, "
        "already ordered by entrenchment (confidence descending, then "
        "declared structure order):\n\n"
        f"{json.dumps(active_steps, indent=2, ensure_ascii=False)}\n\n"
        "Decide per your system prompt's policy and respond with only the "
        "JSON decision object."
    )


# ---------------------------------------------------------------------------
# Main tool handler
# ---------------------------------------------------------------------------


async def arbitrate_inference_conflict(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    conclusion_id = arguments.get("conclusion_id")
    if not conclusion_id:
        return missing_parameter("conclusion_id")
    if not isinstance(session_id, str):
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    # 1. Gather the competing active steps -- same read-only operation
    #    explain_knowledge already uses for an object_id, so the two
    #    tools never disagree about ranking/shape.
    op = ExplainInferenceOperation(
        "explain_inference",
        knowledge_structure=session.knowledge_structure,
        object_id=conclusion_id,
    )
    result = await runtime.executor.execute(op, session)
    if not result.succeeded:
        return internal_error(
            f"explain_inference failed for conclusion_id={conclusion_id!r}: {result.error!s}"
        )

    explanation = result.payload or {}
    active_steps = list(explanation.get("active_steps") or [])

    if len(active_steps) < 2:
        return {
            "session_id": session.session_id,
            "conclusion_id": conclusion_id,
            "conflict": False,
            "message": (
                "Fewer than two active InferenceSteps conclude this object -- "
                "nothing to arbitrate."
            ),
            "active_steps": active_steps,
        }

    active_step_ids = {s.get("step_id") for s in active_steps}

    # 2. Reach a decision, if any of the three paths applies.
    winner_id = arguments.get("winner_id")
    decision: dict[str, Any] | None = None
    decision_source: str | None = None

    if winner_id:
        if winner_id not in active_step_ids:
            return invalid_parameter("winner_id", winner_id, sorted(active_step_ids))
        decision = {
            "winner_step_id": winner_id,
            "reasoning": arguments.get("reasoning") or "Caller-supplied resolution.",
            "runner_up_ids": sorted(active_step_ids - {winner_id}),
            "confidence_in_decision": None,
        }
        decision_source = "caller"

    elif arguments.get("auto_resolve"):
        model = arguments.get("model") or None
        max_tokens = int(
            arguments.get("max_tokens")
            or os.environ.get("CKS_ARBITER_MAX_TOKENS", "1024")
        )
        prompt = _build_arbiter_prompt(conclusion_id, active_steps)
        try:
            raw_output, model_used = _call_llm(prompt, model=model, max_tokens=max_tokens)
        except RuntimeError as exc:
            return internal_error(f"LLM arbiter call failed: {exc}")

        try:
            json_str = llm_providers.extract_json(raw_output)
            parsed = json.loads(json_str)
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "error": "llm_output_parse_error",
                "message": str(exc),
                "raw_output": raw_output[:1000],
            }

        parsed_winner = parsed.get("winner_step_id")
        if parsed_winner not in active_step_ids:
            return {
                "error": "invalid_arbiter_decision",
                "message": (
                    f"Arbiter chose winner_step_id={parsed_winner!r}, which is "
                    f"not among the active steps {sorted(active_step_ids)}."
                ),
                "raw_decision": parsed,
            }
        decision = {
            "winner_step_id": parsed_winner,
            "reasoning": parsed.get("reasoning"),
            "runner_up_ids": list(
                parsed.get("runner_up_ids") or sorted(active_step_ids - {parsed_winner})
            ),
            "confidence_in_decision": parsed.get("confidence_in_decision"),
            "model_used": model_used,
        }
        decision_source = "auto_resolve"

    response: dict[str, Any] = {
        "session_id": session.session_id,
        "conclusion_id": conclusion_id,
        "conflict": True,
        "active_steps": active_steps,
        "policy": _ARBITER_POLICY,
    }
    if decision is not None:
        response["decision"] = decision
        response["decision_source"] = decision_source

    # 3. Optionally apply the decision.
    if arguments.get("commit"):
        if decision is None:
            return {
                "error": "missing_decision",
                "message": (
                    "commit=true requires either 'winner_id' (your own "
                    "decision) or 'auto_resolve': true (let this tool decide)."
                ),
            }
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session.session_id,
                "operations": [
                    {
                        "type": "resolve_inference_conflict",
                        "conclusion_id": conclusion_id,
                        "winner_id": decision["winner_step_id"],
                    }
                ],
                "extensions": ["inference_confidence_conflict", "supersession_chain"],
            },
        )
        response["commit_result"] = evolve_result

    return response
