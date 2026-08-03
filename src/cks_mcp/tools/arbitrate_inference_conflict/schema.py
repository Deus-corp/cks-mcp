"""Input schema definitions for the arbitrate_inference_conflict tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

ARBITRATE_INFERENCE_CONFLICT_SCHEMA = {
    "name": "arbitrate_inference_conflict",
    "description": (
        "Resolve an InferenceConfidenceConflict (ADR-001): two or more active "
        "InferenceSteps that conclude the same object but disagree. Always "
        "returns the competing 'active_steps' (already ranked by entrenchment "
        "-- see explain_knowledge) plus a 'policy' describing the arbitration "
        "criteria, so a client that is itself an LLM (this server is "
        "currently tested against Claude Desktop) can weigh them and decide "
        "without any extra LLM call. Three ways to reach and apply a "
        "decision, from most to least interactive: "
        "(1) read 'active_steps'/'policy' yourself and call this tool again "
        "with 'winner_id' set to your own choice; "
        "(2) set 'auto_resolve': true to have this tool make its own LLM "
        "call (useful for an unattended Critic agent with no interactive "
        "client -- see list_gossip_conflicts) using the same criteria; "
        "(3) skip this tool for the decision and apply evolve_knowledge's "
        "'resolve_inference_conflict' operation directly yourself. "
        "In all three cases, add 'commit': true to have this tool apply the "
        "winning step via evolve_knowledge and persist a new version, "
        "instead of just returning the decision for you to apply. "
        "For several disputed conclusions at once -- e.g. working through a "
        "list_gossip_conflicts backlog -- use 'conclusion_ids' (batch mode; "
        "see its own parameter description) instead of 'conclusion_id': "
        "with 'auto_resolve', every conclusion still needing a decision is "
        "resolved in ONE combined LLM call rather than one per conflict, and "
        "'commit' applies the whole batch as ONE new version."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session containing the disputed conclusion.",
            },
            "conclusion_id": {
                "type": "string",
                "description": (
                    "The object_id whose active InferenceSteps may conflict "
                    "(same meaning as explain_knowledge's 'object_id'). "
                    "Mutually exclusive with 'conclusion_ids' (batch mode)."
                ),
            },
            "conclusion_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Batch mode: resolve several disputed conclusions in "
                    "this session in one call instead of one round trip per "
                    "conclusion_id -- built for an unattended Critic agent "
                    "working through a backlog (e.g. from "
                    "list_gossip_conflicts). Mutually exclusive with "
                    "'conclusion_id'/'winner_id' (use 'winners' instead). "
                    "With 'auto_resolve': true, every conclusion_id still "
                    "needing a decision after 'winners' is applied is "
                    "resolved in ONE combined LLM call, not one call each. "
                    "Returns 'results' (one entry per conclusion_id, same "
                    "per-item shape as the single-conclusion response) "
                    "instead of the top-level 'conflict'/'active_steps'/"
                    "'decision' fields -- a bad or conflict-free entry only "
                    "affects its own result, never the rest of the batch. "
                    "'commit': true applies every resolved conclusion in "
                    "ONE evolve_knowledge call (one new version for the "
                    "whole batch, not one per conclusion_id)."
                ),
            },
            "winner_id": {
                "type": "string",
                "description": (
                    "Optional. Your own decision: the step_id (from the "
                    "returned 'active_steps') you've already determined is "
                    "strongest. When given, no LLM call is made by this "
                    "tool regardless of 'auto_resolve'. Must be one of the "
                    "active step ids for this conclusion_id. Applies only "
                    "to 'conclusion_id' -- use 'winners' with "
                    "'conclusion_ids' instead."
                ),
            },
            "winners": {
                "type": "object",
                "description": (
                    "Batch counterpart to 'winner_id': an object mapping "
                    "each conclusion_id to your own already-decided winner "
                    "step id, e.g. {'obj-1': 'step-a', 'obj-2': 'step-c'}. "
                    "Only used with 'conclusion_ids'. A conclusion_id not "
                    "covered here falls through to 'auto_resolve' (if set) "
                    "or is returned undecided for you to resolve next time."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Optional. Your rationale for 'winner_id', recorded "
                    "alongside the decision in the response for an audit "
                    "trail. Ignored if 'winner_id' is not given."
                ),
            },
            "auto_resolve": {
                "type": "boolean",
                "description": (
                    "Optional, default false. If true and 'winner_id' is not "
                    "given, this tool makes its own LLM call (provider per "
                    "CKS_LLM_PROVIDER -- 'auto' | 'ollama' | 'anthropic', "
                    "same as construct_knowledge) applying the arbitration "
                    "policy and returns its decision."
                ),
            },
            "commit": {
                "type": "boolean",
                "description": (
                    "Optional, default false. If true, apply the decision "
                    "-- from 'winner_id' or from 'auto_resolve' -- via "
                    "evolve_knowledge's 'resolve_inference_conflict' "
                    "operation and commit a new version. Requires one of "
                    "'winner_id' or 'auto_resolve' to actually supply a "
                    "decision; otherwise returns an error rather than "
                    "guessing."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional model override for 'auto_resolve' (default: "
                    "CKS_ARBITER_MODEL / CKS_LLM_MODEL env var, else "
                    "'claude-sonnet-4-6'). Ignored otherwise."
                ),
            },
            "max_tokens": {
                "type": "integer",
                "description": (
                    "Optional max_tokens override for 'auto_resolve' "
                    "(default: CKS_ARBITER_MAX_TOKENS env var, else 1024 -- "
                    "the decision is a small JSON object, not prose). "
                    "Ignored otherwise."
                ),
            },
        },
        "required": ["session_id"],
    },
}
