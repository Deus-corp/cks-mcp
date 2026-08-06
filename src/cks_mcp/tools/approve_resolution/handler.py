"""
approve_resolution: apply a resolution -- typically the
``proposed_resolution`` a prior ``review_dead_letter`` call returned,
possibly with manual edits -- to a dead-lettered conflict task.

This tool is purely mechanical: it does not decide *how* to resolve
anything itself. It only (1) validates that the caller's chosen
resolution tool actually matches the task's own ``task_type`` (so a
gossip resolution can't accidentally be applied to an inference-conflict
task), (2) calls that resolution tool with the given arguments, and (3)
marks the task complete via ``complete_conflict_task`` if -- and only
if -- the resolution tool's own result indicates success. If the
resolution fails, the task is left exactly as it was (still DEAD, for
another review/approve attempt or a rejection).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.tools.arbitrate_inference_conflict.handler import (
    arbitrate_inference_conflict,
)
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.refresh_verification.handler import refresh_verification
from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction
from cks_mcp.tools.resolve_gossip_conflict.handler import resolve_gossip_conflict
from cks_mcp.tools.resolve_temporal_conflict.handler import (
    resolve_temporal_conflict as resolve_temporal_conflict_tool,
)

# Which resolution tool is legitimate for which dead-lettered
# task_type -- mirrors review_dead_letter's own _PROPOSERS mapping and
# cks_mcp.critic_agent's _RESOLVERS, so a resolution built by hand (or
# edited from review_dead_letter's proposal) can never be applied to
# the wrong kind of conflict.
_TASK_TYPE_TO_TOOL = {
    "gossip_conflict": "resolve_gossip_conflict",
    "inference_conflict": "arbitrate_inference_conflict",
    "provenance_conflict": "refresh_verification",
    "temporal_conflict": "resolve_temporal_conflict",
    "contradiction_detected": "resolve_contradiction",
}

_RESOLUTION_HANDLERS = {
    "resolve_gossip_conflict": resolve_gossip_conflict,
    "arbitrate_inference_conflict": arbitrate_inference_conflict,
    "refresh_verification": refresh_verification,
    "resolve_temporal_conflict": resolve_temporal_conflict_tool,
    "resolve_contradiction": resolve_contradiction,
}


def _resolution_succeeded(tool_name: str, result: dict[str, Any]) -> bool:
    """
    Mechanical success check, mirroring how cks_mcp.critic_agent's own
    per-type resolvers decide whether a call actually resolved a
    conflict.

    resolve_gossip_conflict is a special case: unlike every other
    resolution tool, it never takes a 'commit' argument and never
    returns a top-level 'error' for the ordinary "still conflicting"
    outcome -- a probe that finds structural conflicts (or one that
    was never given 'auto_resolve') comes back as
    ``{'merged': False, 'conflicts': [...]}``, which is a legitimate,
    error-free response but not a resolution. So success there means
    exactly ``merged: True`` (see critic_agent.resolve_gossip_conflict,
    which draws the same line).

    Every other resolution tool here always commits when it succeeds
    (review_dead_letter's proposals all set 'commit': true, or --
    resolve_temporal_conflict's 'ignore' action, resolve_contradiction
    with nothing left to resolve -- have nothing to commit at all): a
    top-level 'error' means the call itself failed; a failing
    'commit_result' means a decision was reached but never applied; a
    present, error-free 'commit_result' means it was applied; and no
    'commit_result' at all (with no top-level 'error') means there was
    genuinely nothing left to do, which counts as resolved.
    """
    if not isinstance(result, dict):
        return False

    if tool_name == "resolve_gossip_conflict":
        return bool(result.get("merged"))

    if result.get("error"):
        return False

    commit_result = result.get("commit_result")
    if commit_result is not None:
        return not (isinstance(commit_result, dict) and commit_result.get("error"))

    return True


async def approve_resolution(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = arguments["task_id"]
    resolution = arguments["resolution"]

    if not isinstance(resolution, dict):
        return {
            "approved": False,
            "task_id": task_id,
            "error": "invalid_parameter",
            "message": "'resolution' must be an object of shape {'tool': ..., 'arguments': {...}}.",
        }

    tool_name = resolution.get("tool")
    tool_arguments = resolution.get("arguments")

    if not tool_name or not isinstance(tool_arguments, dict):
        return {
            "approved": False,
            "task_id": task_id,
            "error": "invalid_parameter",
            "message": "'resolution' must include a 'tool' name and an 'arguments' object.",
        }

    if not runtime.storage.supports_outbox:
        return {
            "approved": False,
            "task_id": task_id,
            "error": "not_supported",
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage) -- there is no dead-letter "
                "queue to approve against."
            ),
        }

    tasks = await runtime.storage.list_dead_letter_tasks()
    task = next((t for t in tasks if t.task_id == task_id), None)
    if task is None:
        return {
            "approved": False,
            "task_id": task_id,
            "error": "task_not_dead_lettered",
            "message": (
                f"Task {task_id!r} was not found among DEAD-lettered tasks -- "
                "it may not exist, or it may not currently be in the DEAD state."
            ),
        }

    expected_tool = _TASK_TYPE_TO_TOOL.get(task.task_type)
    if expected_tool is None:
        return {
            "approved": False,
            "task_id": task_id,
            "error": "unknown_task_type",
            "message": f"No known resolution tool for task_type={task.task_type!r}.",
        }
    if tool_name != expected_tool:
        return {
            "approved": False,
            "task_id": task_id,
            "error": "tool_task_type_mismatch",
            "message": (
                f"resolution.tool={tool_name!r} does not match the resolution "
                f"tool for task_type={task.task_type!r} (expected {expected_tool!r})."
            ),
        }

    handler = _RESOLUTION_HANDLERS[tool_name]
    resolution_result = await handler(runtime, tool_arguments)

    if not _resolution_succeeded(tool_name, resolution_result):
        return {
            "approved": False,
            "task_id": task_id,
            "resolution_result": resolution_result,
            "message": (
                "Resolution was not successful -- the task remains DEAD. "
                "See 'resolution_result' for details."
            ),
        }

    await complete_conflict_task(runtime, {"task_id": task_id})

    return {
        "approved": True,
        "task_id": task_id,
        "resolution_result": resolution_result,
    }
