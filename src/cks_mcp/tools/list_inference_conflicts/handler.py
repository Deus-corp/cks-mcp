"""
list_inference_conflicts: drain (or peek) the queue of reasoning-
staleness findings escalated by ``InferenceStalenessSweeper``
(cks-runtime, ADR-009) that no one has looked at yet.

This is a read on ``conflict_inbox`` (see ``cks_mcp.conflict_inbox``),
not on the Runtime -- ``session_id`` is a filter, not a session this
tool operates against, so unlike most other tools here it takes no
``runtime`` state into account and never requires an existing session.
Each returned record's ``diagnostics`` is the same
``{"code", "severity", "message", "location"}`` shape
``evolve_knowledge``/``validate_knowledge`` already return; a
``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`` entry's ``message`` names the
disputed ``conclusion_id`` in quotes -- pull it from there to call
``arbitrate_inference_conflict`` with ``session_id``/``conclusion_id``.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.conflict_inbox import conflict_inbox


async def list_inference_conflicts(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return buffered inference-staleness findings, draining them unless peek=true."""
    session_id = arguments.get("session_id")
    peek = bool(arguments.get("peek", False))

    conflicts = await conflict_inbox.list_inference(session_id=session_id, drain=not peek)

    return {"conflicts": conflicts, "count": len(conflicts)}