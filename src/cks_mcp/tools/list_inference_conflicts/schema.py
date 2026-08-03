"""Input schema definition for the list_inference_conflicts tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_INFERENCE_CONFLICTS_SCHEMA = {
    "name": "list_inference_conflicts",
    "description": "Return reasoning-staleness findings escalated by a background "
    "InferenceStalenessSweeper (cks-runtime, ADR-009; runs by default at "
    "RuntimeConfig.inference_sweep_interval) that no one has resolved yet -- the "
    "proactive counterpart to arbitrate_inference_conflict's on-demand check, for "
    "conflicts a background sweep found in a session nobody happened to re-check. "
    "Each record has 'session_id' (the session the finding belongs to), "
    "'version_id' (that session's latest version when the sweep ran), "
    "'diagnostics' (a list of {'code', 'severity', 'message', 'location'} entries -- "
    "'code' is 'CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT' or 'CKS-EXT-STALE-PREMISE'; "
    "for a confidence-conflict entry, 'message' names the disputed conclusion id in "
    "quotes -- read it from there and call arbitrate_inference_conflict with that "
    "session_id/conclusion_id to resolve it), 'detected_at', and 'record_id'. "
    "Returns an empty list if the sweeper is disabled (inference_sweep_interval=None) "
    "or nothing has been found yet. Records are removed from the queue once "
    "returned unless 'peek' is set, so a Critic agent that lists conflicts is "
    "expected to act on (or re-list with peek=true to keep) what it gets back.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Only return (and drain) findings for this session. "
                "Omit to return findings for every session.",
            },
            "peek": {
                "type": "boolean",
                "description": "If true, return matching findings without removing "
                "them from the queue. Default: false (drain on read).",
                "default": False,
            },
        },
        "required": [],
    },
}