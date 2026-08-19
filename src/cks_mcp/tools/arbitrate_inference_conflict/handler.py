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

Batch mode (ADR-008-adjacent status update): pass 'conclusion_ids'
instead of 'conclusion_id' to resolve several disputed conclusions in
one call -- see _arbitrate_batch below. Built for an unattended Critic
agent working through a list_gossip_conflicts-style backlog, where a
separate LLM call per conflict is pure overhead: 'auto_resolve' makes
exactly ONE combined LLM call (_call_llm_batch) covering every
conclusion_id still undecided after 'winners' (the batch counterpart
of 'winner_id') is applied, and 'commit' applies the whole batch as
ONE evolve_knowledge call/version instead of one per conclusion_id.

Environment variables (auto_resolve only; same names/semantics as
construct_knowledge's, see llm/providers/):
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

from cks_mcp.errors import (
    internal_error,
    invalid_parameter,
    missing_parameter,
    session_not_found,
)
from cks_mcp.llm import providers as llm_providers
from cks_mcp.tools.evolve.handler import evolve_knowledge

# ---------------------------------------------------------------------------
# The arbitration policy
# ---------------------------------------------------------------------------
#
# Returned verbatim as the response's "policy" field (path 1 above) and
# embedded in the LLM system prompt (path 2) -- one statement of the
# criteria, not two copies that could drift apart.

_ARBITER_CRITERIA = """\
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
winner_step_id.\
"""

_ARBITER_POLICY = (
    _ARBITER_CRITERIA
    + "\n\n"
    + """\
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
)

_ARBITER_SYSTEM_PROMPT = _ARBITER_POLICY

# ADR-008-adjacent status update: batch mode. Same criteria as
# _ARBITER_POLICY above -- deliberately the identical _ARBITER_CRITERIA
# text, not a separately-maintained copy that could drift -- but a
# different response shape, since a batch request expects one decision
# per conclusion_id back from a single combined call instead of one
# object for one conclusion. See _arbitrate_batch's docstring for why
# this is one LLM call, not N.
_ARBITER_BATCH_POLICY = (
    _ARBITER_CRITERIA
    + "\n\n"
    + """\
You will be given several disputed conclusions to decide in this one request \
instead of one at a time. Apply the same criteria to each independently -- \
one conclusion's evidence must not influence another's decision. Respond with \
ONLY a JSON array, no markdown fences and no commentary before or after it, \
containing exactly one decision object per conclusion_id you were given, in \
the same order, each of this shape:
{
  "conclusion_id": "<the conclusion_id this decision is for>",
  "winner_step_id": "<step_id of the InferenceStep that should remain active>",
  "reasoning": "<2-4 sentences citing which of the criteria above decided it>",
  "runner_up_ids": ["<step_id>", "..."],
  "confidence_in_decision": <0.0-1.0, your own confidence in this call, distinct \
from any confidence field on the steps themselves>
}
"""
)

_ARBITER_BATCH_SYSTEM_PROMPT = _ARBITER_BATCH_POLICY


# ---------------------------------------------------------------------------
# LLM call -- thin wrappers around cks_mcp.llm.providers, binding in this
# tool's own _ARBITER_SYSTEM_PROMPT. Same shape as construct_knowledge's
# _call_ollama/_call_anthropic/_call_llm so provider-selection behavior
# (and how tests patch it) stays consistent across tools that call an LLM.
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_ollama(
        prompt,
        system_prompt=_ARBITER_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name="arbitrate_inference_conflict",
    )


def _call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_anthropic(
        prompt,
        system_prompt=_ARBITER_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name="arbitrate_inference_conflict",
    )


def _call_ollama_batch(prompt: str, model: str, max_tokens: int) -> str:
    """Batch counterpart of _call_ollama, bound to _ARBITER_BATCH_SYSTEM_PROMPT."""
    return llm_providers.call_ollama(
        prompt,
        system_prompt=_ARBITER_BATCH_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name="arbitrate_inference_conflict",
    )


def _call_anthropic_batch(prompt: str, model: str, max_tokens: int) -> str:
    """Batch counterpart of _call_anthropic, bound to _ARBITER_BATCH_SYSTEM_PROMPT."""
    return llm_providers.call_anthropic(
        prompt,
        system_prompt=_ARBITER_BATCH_SYSTEM_PROMPT,
        model=model,
        max_tokens=max_tokens,
        tool_name="arbitrate_inference_conflict",
    )


def _default_model() -> str:
    return os.environ.get("CKS_ARBITER_MODEL") or os.environ.get(
        "CKS_LLM_MODEL", "claude-sonnet-4-6"
    )


def _dispatch_llm(
    prompt: str,
    *,
    model: str | None,
    max_tokens: int,
    ollama_fn,
    anthropic_fn,
    unavailable_hint: str,
) -> tuple[str, str]:
    """
    Shared provider dispatch ('auto' | 'ollama' | 'anthropic', same
    CKS_LLM_PROVIDER env var construct_knowledge already uses) behind
    both _call_llm (single conclusion_id) and _call_llm_batch (the
    combined batch call) -- only the system prompt bound into
    ollama_fn/anthropic_fn and the no-provider-available hint text
    differ between the two. ollama_fn/anthropic_fn are looked up by
    the caller at its own call time (not defaulted here), so patching
    e.g. ``_call_anthropic`` in a test still takes effect the same way
    it always has.
    """
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return ollama_fn(prompt, m, max_tokens), m

    if provider == "anthropic":
        m = model or _default_model()
        return anthropic_fn(prompt, m, max_tokens), m

    if provider != "auto":
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', or 'anthropic'."
        )

    if llm_providers.ollama_available():
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return ollama_fn(prompt, m, max_tokens), m

    m = model or _default_model()
    try:
        return anthropic_fn(prompt, m, max_tokens), m
    except RuntimeError as exc:
        if "ANTHROPIC_API_KEY" not in str(exc):
            raise
        raise RuntimeError(unavailable_hint) from exc


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> tuple[str, str]:
    """
    Route the arbitration prompt to whichever LLM provider is configured
    or available. Returns (raw_text, model_used). Raises RuntimeError
    with a message listing every option -- including the non-LLM escape
    hatch of supplying 'winner_id' directly -- when no provider works.
    """
    return _dispatch_llm(
        prompt,
        model=model,
        max_tokens=max_tokens,
        ollama_fn=_call_ollama,
        anthropic_fn=_call_anthropic,
        unavailable_hint=(
            "No LLM provider available for arbitrate_inference_conflict's "
            "auto_resolve. Options: (1) run a local model -- `ollama serve` "
            "+ `ollama pull llama3.2` -- no API key needed; (2) set "
            "ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; (3) skip "
            "auto_resolve entirely -- read this tool's 'active_steps' and "
            "'policy' yourself (this MCP server is typically already being "
            "driven by an LLM client) and call it again with 'winner_id' "
            "set to your own decision."
        ),
    )


def _call_llm_batch(prompt: str, *, model: str | None, max_tokens: int) -> tuple[str, str]:
    """
    Same provider dispatch as _call_llm, but bound to
    _ARBITER_BATCH_SYSTEM_PROMPT via _call_ollama_batch/_call_anthropic_batch
    -- the single combined LLM call that resolves every conclusion_id
    in a batch arbitrate_inference_conflict request still needing a
    decision, in one round trip instead of one per conclusion_id.
    """
    return _dispatch_llm(
        prompt,
        model=model,
        max_tokens=max_tokens,
        ollama_fn=_call_ollama_batch,
        anthropic_fn=_call_anthropic_batch,
        unavailable_hint=(
            "No LLM provider available for arbitrate_inference_conflict's "
            "batch auto_resolve. Options: (1) run a local model -- `ollama "
            "serve` + `ollama pull llama3.2` -- no API key needed; (2) set "
            "ANTHROPIC_API_KEY and CKS_LLM_PROVIDER=anthropic; (3) skip "
            "auto_resolve and call this tool once per conclusion_id instead."
        ),
    )


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


def _build_batch_arbiter_prompt(conflicts: list[tuple[str, list[dict[str, Any]]]]) -> str:
    """
    Batch counterpart to _build_arbiter_prompt: lists every conclusion
    still needing a decision in one prompt, each tagged with its own
    conclusion_id, so a single combined LLM call can return one
    decision per entry instead of one call per conclusion_id.
    """
    blocks = []
    for conclusion_id, active_steps in conflicts:
        blocks.append(
            f"conclusion_id: {conclusion_id!r}\n"
            f"{len(active_steps)} active InferenceSteps, already ordered by "
            "entrenchment (confidence descending, then declared structure "
            f"order):\n{json.dumps(active_steps, indent=2, ensure_ascii=False)}"
        )
    return (
        f"{len(conflicts)} disputed conclusions to resolve in this one pass:\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\nDecide per your system prompt's policy and respond with only "
        "the JSON array of decisions, one entry per conclusion_id above."
    )


# ---------------------------------------------------------------------------
# Gathering active steps -- shared by the single-conclusion and batch paths
# ---------------------------------------------------------------------------


async def _gather_active_steps(
    runtime: Runtime, session: Any, conclusion_id: str
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """
    Run the same read-only ExplainInferenceOperation the single-item
    path (and explain_knowledge) uses for one conclusion_id. Returns
    (active_steps, None) on success or (None, error_dict) on failure --
    shared by both arbitrate_inference_conflict's single-conclusion path
    and its batch path, so the two never disagree about how a
    conclusion's active steps are gathered.
    """
    op = ExplainInferenceOperation(
        "explain_inference",
        knowledge_structure=session.knowledge_structure,
        object_id=conclusion_id,
    )
    result = await runtime.executor.execute(op, session)
    if not result.succeeded:
        return None, internal_error(
            f"explain_inference failed for conclusion_id={conclusion_id!r}: {result.error!s}"
        )
    explanation = result.payload or {}
    return list(explanation.get("active_steps") or []), None


def _extract_json_array(raw: str) -> str:
    """
    Batch counterpart to llm_providers.extract_json: that helper only
    ever looks for a JSON *object* (starting from the first '{'),
    which is the right shape for every other LLM-facing tool here but
    wrong for a batch arbiter response -- a JSON *array* of decision
    objects, one per conclusion_id. Using extract_json unmodified on a
    batch response would find and return just the *first* decision
    object's braces, silently discarding every other entry in the
    array. Same brace/bracket-matching approach as extract_json --
    strips markdown fences, tolerates trailing commentary, reports
    truncated output as unbalanced rather than a confusing parse error
    -- just anchored on '[' / ']' instead of '{' / '}'.
    """
    stripped = raw.strip()

    start = stripped.find("[")
    if start == -1:
        raise ValueError("No JSON array found in LLM output.")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]

    raise ValueError("Unbalanced brackets in LLM output -- could not extract JSON array.")


# ---------------------------------------------------------------------------
# Main tool handler
# ---------------------------------------------------------------------------


async def arbitrate_inference_conflict(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    conclusion_id = arguments.get("conclusion_id")
    conclusion_ids = arguments.get("conclusion_ids")
    stale_premise_ids = arguments.get("stale_premise_ids")

    if stale_premise_ids is not None and (conclusion_id or conclusion_ids is not None):
        return {
            "error": "invalid_parameter",
            "message": (
                "'stale_premise_ids' resolves a different diagnostic "
                "(CKS-EXT-STALE-PREMISE) than 'conclusion_id'/'conclusion_ids' "
                "(CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT) -- call this tool "
                "once per diagnostic type instead of mixing them."
            ),
        }
    if stale_premise_ids is not None:
        return await _resolve_stale_premises(runtime, arguments)

    if conclusion_id and conclusion_ids is not None:
        return {
            "error": "invalid_parameter",
            "message": (
                "Provide either 'conclusion_id' (single) or 'conclusion_ids' "
                "(batch), not both."
            ),
        }
    if arguments.get("winner_id") and conclusion_ids is not None:
        return {
            "error": "invalid_parameter",
            "message": (
                "'winner_id' applies to a single 'conclusion_id'. Use "
                "'winners' (a {conclusion_id: winner_step_id} object) with "
                "'conclusion_ids' instead."
            ),
        }
    if conclusion_ids is not None:
        return await _arbitrate_batch(runtime, arguments)

    session_id = arguments.get("session_id")
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
    active_steps, error = await _gather_active_steps(runtime, session, conclusion_id)
    if error is not None:
        return error
    assert active_steps is not None  # narrowed by the check above

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

    active_step_ids = {s["step_id"] for s in active_steps}

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


# ---------------------------------------------------------------------------
# Batch mode: several conclusion_ids in one call
# ---------------------------------------------------------------------------


async def _arbitrate_batch(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Batch counterpart to the single-conclusion path above: resolve
    several InferenceConfidenceConflicts in one call instead of one
    round trip per conclusion_id -- built for an unattended Critic
    agent working through a backlog (e.g. from list_gossip_conflicts),
    where a separate LLM call per conflict is pure overhead.

    Every conclusion_id in 'conclusion_ids' gathers its own
    active_steps independently (a cheap, read-only operation -- no
    saving here), but when 'auto_resolve' is set, every conclusion_id
    still needing a decision after 'winners' is applied is resolved in
    exactly ONE combined LLM call (_call_llm_batch /
    _build_batch_arbiter_prompt), not one call per conclusion_id --
    that consolidation is the entire point of this mode. A bad or
    conflict-free entry only affects its own item in 'results'; it
    never aborts the rest of the batch. 'commit': true then applies
    every resolved conclusion (from 'winners' and/or 'auto_resolve') as
    ONE evolve_knowledge call, so the whole batch lands as a single new
    version instead of one version per conclusion_id.
    """
    conclusion_ids = arguments.get("conclusion_ids")
    if not isinstance(conclusion_ids, list) or not conclusion_ids:
        return {
            "error": "invalid_parameter",
            "message": "'conclusion_ids' must be a non-empty list of object ids.",
        }
    if not all(isinstance(c, str) and c for c in conclusion_ids):
        return {
            "error": "invalid_parameter",
            "message": "'conclusion_ids' must contain only non-empty strings.",
        }
    if len(set(conclusion_ids)) != len(conclusion_ids):
        return {
            "error": "invalid_parameter",
            "message": "'conclusion_ids' contains duplicates.",
        }

    winners = arguments.get("winners") or {}
    if not isinstance(winners, dict):
        return {
            "error": "invalid_parameter",
            "message": (
                "'winners' must be an object mapping conclusion_id to winner_step_id."
            ),
        }

    session_id = arguments.get("session_id")
    if not isinstance(session_id, str):
        return missing_parameter("session_id")
    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    items: list[dict[str, Any]] = []
    # Entries still needing a decision after 'winners', paired with the
    # active_step_ids set needed to validate the arbiter's eventual
    # answer for that one entry.
    pending_auto: list[dict[str, Any]] = []

    for cid in conclusion_ids:
        active_steps, error = await _gather_active_steps(runtime, session, cid)
        if error is not None:
            items.append({"conclusion_id": cid, **error})
            continue
        assert active_steps is not None  # narrowed by the check above

        if len(active_steps) < 2:
            items.append(
                {
                    "conclusion_id": cid,
                    "conflict": False,
                    "message": (
                        "Fewer than two active InferenceSteps conclude this "
                        "object -- nothing to arbitrate."
                    ),
                    "active_steps": active_steps,
                }
            )
            continue

        active_step_ids = {s["step_id"] for s in active_steps}
        item: dict[str, Any] = {
            "conclusion_id": cid,
            "conflict": True,
            "active_steps": active_steps,
        }

        caller_winner = winners.get(cid)
        if caller_winner:
            if caller_winner not in active_step_ids:
                item.update(invalid_parameter(f"winners[{cid!r}]", caller_winner, sorted(active_step_ids)))
                items.append(item)
                continue
            item["decision"] = {
                "winner_step_id": caller_winner,
                "reasoning": "Caller-supplied resolution.",
                "runner_up_ids": sorted(active_step_ids - {caller_winner}),
                "confidence_in_decision": None,
            }
            item["decision_source"] = "caller"
            items.append(item)
            continue

        if arguments.get("auto_resolve"):
            # Resolved together below, in the one combined LLM call --
            # not here, and not one call per conclusion_id.
            pending_auto.append({"item": item, "active_step_ids": active_step_ids})
            items.append(item)
            continue

        # Interactive path: no decision reached for this conclusion --
        # caller reads active_steps/policy and calls again (per-item
        # 'winner_id', or a 'winners' entry, next time).
        items.append(item)

    if pending_auto:
        model = arguments.get("model") or None
        max_tokens = int(
            arguments.get("max_tokens") or os.environ.get("CKS_ARBITER_MAX_TOKENS", "1024")
        )
        prompt = _build_batch_arbiter_prompt(
            [(p["item"]["conclusion_id"], p["item"]["active_steps"]) for p in pending_auto]
        )
        try:
            raw_output, model_used = _call_llm_batch(prompt, model=model, max_tokens=max_tokens)
        except RuntimeError as exc:
            batch_error = internal_error(f"LLM arbiter call failed: {exc}")
            for p in pending_auto:
                p["item"].update(batch_error)
        else:
            try:
                json_str = _extract_json_array(raw_output)
                parsed = json.loads(json_str)
            except (ValueError, json.JSONDecodeError) as exc:
                parse_error = {
                    "error": "llm_output_parse_error",
                    "message": str(exc),
                    "raw_output": raw_output[:1000],
                }
                for p in pending_auto:
                    p["item"].update(parse_error)
            else:
                if not isinstance(parsed, list):
                    shape_error = {
                        "error": "invalid_arbiter_decision",
                        "message": "Batch arbiter response was not a JSON array.",
                        "raw_decision": parsed,
                    }
                    for p in pending_auto:
                        p["item"].update(shape_error)
                else:
                    by_conclusion = {
                        d.get("conclusion_id"): d for d in parsed if isinstance(d, dict)
                    }
                    for p in pending_auto:
                        cid = p["item"]["conclusion_id"]
                        active_step_ids = p["active_step_ids"]
                        decision_raw = by_conclusion.get(cid)
                        if decision_raw is None:
                            p["item"].update(
                                {
                                    "error": "invalid_arbiter_decision",
                                    "message": (
                                        "Batch arbiter response did not include a "
                                        f"decision for conclusion_id={cid!r}."
                                    ),
                                    "raw_decision": parsed,
                                }
                            )
                            continue
                        parsed_winner = decision_raw.get("winner_step_id")
                        if parsed_winner not in active_step_ids:
                            p["item"].update(
                                {
                                    "error": "invalid_arbiter_decision",
                                    "message": (
                                        f"Arbiter chose winner_step_id={parsed_winner!r} "
                                        f"for conclusion_id={cid!r}, which is not among "
                                        f"the active steps {sorted(active_step_ids)}."
                                    ),
                                    "raw_decision": decision_raw,
                                }
                            )
                            continue
                        p["item"]["decision"] = {
                            "winner_step_id": parsed_winner,
                            "reasoning": decision_raw.get("reasoning"),
                            "runner_up_ids": list(
                                decision_raw.get("runner_up_ids")
                                or sorted(active_step_ids - {parsed_winner})
                            ),
                            "confidence_in_decision": decision_raw.get("confidence_in_decision"),
                            "model_used": model_used,
                        }
                        p["item"]["decision_source"] = "auto_resolve"

    response: dict[str, Any] = {
        "session_id": session.session_id,
        "results": items,
        "policy": _ARBITER_POLICY,
    }

    if arguments.get("commit"):
        operations = [
            {
                "type": "resolve_inference_conflict",
                "conclusion_id": item["conclusion_id"],
                "winner_id": item["decision"]["winner_step_id"],
            }
            for item in items
            if "decision" in item
        ]
        if not operations:
            response["error"] = "missing_decision"
            response["message"] = (
                "commit=true requires at least one resolved conclusion in "
                "the batch -- via 'winners' or 'auto_resolve'."
            )
            return response
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session.session_id,
                "operations": operations,
                "extensions": ["inference_confidence_conflict", "supersession_chain"],
            },
        )
        response["commit_result"] = evolve_result

    return response


async def _resolve_stale_premises(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve CKS-EXT-STALE-PREMISE findings: an active InferenceStep
    whose 'premises' list includes a step_id that has itself since been
    superseded. The fix is mechanical -- repoint every stale premise
    citation to the current live successor (walking the supersession
    chain), no LLM, no arbitration -- applied via one
    ``evolve_knowledge`` call when ``commit`` is true, or returned as a
    dry-run otherwise.
    """
    stale_premise_ids = arguments.get("stale_premise_ids")
    if not isinstance(stale_premise_ids, list) or not stale_premise_ids:
        return {
            "error": "invalid_parameter",
            "message": "'stale_premise_ids' must be a non-empty list of step ids.",
        }
    if not all(isinstance(s, str) and s for s in stale_premise_ids):
        return {
            "error": "invalid_parameter",
            "message": "'stale_premise_ids' must contain only non-empty strings.",
        }

    session_id = arguments.get("session_id")
    if not isinstance(session_id, str):
        return missing_parameter("session_id")
    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    items: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []

    for step_id in stale_premise_ids:
        obj = session.knowledge_structure.get(step_id)
        if obj is None:
            items.append({"step_id": step_id, "error": f"Step '{step_id}' not found."})
            continue
        if obj.identity.type != "InferenceStep":
            items.append({"step_id": step_id, "error": f"'{step_id}' is not an InferenceStep."})
            continue

        premises = obj.structure.get("premises") or []
        fixes = {}
        for premise_id in premises:
            successor = _find_live_successor(session.knowledge_structure, premise_id)
            if successor != premise_id:
                fixes[premise_id] = successor

        if not fixes:
            items.append({"step_id": step_id, "resolved": False, "message": "No stale premises found."})
            continue

        new_premises = [fixes.get(p, p) for p in premises]
        items.append({"step_id": step_id, "resolved": True, "fixes": fixes})
        operations.append({
            "type": "update_object",
            "object_id": step_id,
            "structure_patch": {"premises": new_premises},
        })

    response: dict[str, Any] = {
        "session_id": session.session_id,
        "results": items,
    }

    if arguments.get("commit") and operations:
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session.session_id,
                "operations": operations,
                "extensions": ["supersession_chain"],
            },
        )
        response["commit_result"] = evolve_result

    return response


def _find_live_successor(structure, step_id: str) -> str:
    """Walk the superseded_by chain to find the live successor of a step."""
    seen = set()
    current = step_id
    while current not in seen:
        seen.add(current)
        obj = structure.get(current)
        if obj is None or obj.identity.type != "InferenceStep":
            break
        next_id = obj.structure.get("superseded_by")
        if not next_id or next_id == current:
            break
        current = next_id
    return current