"""
check_graph_health: aggregate several existing read-only checks
(check_component_versions, check_graph_freshness, detect_contradictions,
list_dead_lettered_conflicts) plus a direct scan of the graph's
VerificationRecord objects and its raw size into a single 0.0-1.0
health score for a registered graph, so a sweeper or an operator can
tell "is this graph OK" at a glance instead of calling every one of
those tools separately and interpreting the results by hand.

Mechanical, like check_graph_freshness/check_component_versions: no
LLM call, and this never writes back to the graph or session -- it
only reads state that those other tools (and GraphFreshnessSweeper /
GraphAutoUpdateSweeper) already produce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter
from cks_mcp.tools.check_component_versions.handler import check_component_versions
from cks_mcp.tools.check_graph_freshness.handler import check_graph_freshness
from cks_mcp.tools.detect_contradictions.handler import detect_contradictions
from cks_mcp.tools.list_dead_lettered_conflicts.handler import (
    list_dead_lettered_conflicts,
)

_VERIFICATION_RECORD_TYPE = "VerificationRecord"
_CHECKED_AT_KEY = "checked_at"
_VERIFICATION_COVERAGE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# Weights used to combine the individual metric scores into the
# overall health_score. Must sum to 1.0.
_WEIGHT_VERSION_FRESHNESS = 0.3
_WEIGHT_TTL_FRESHNESS = 0.1
_WEIGHT_CONTRADICTIONS = 0.3
_WEIGHT_VERIFICATION_COVERAGE = 0.2
_WEIGHT_DEAD_LETTER = 0.1


def _parse_checked_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _version_freshness_metric(
    runtime: Runtime, name: str
) -> dict[str, Any]:
    result = await check_component_versions(runtime, {"name": name})
    components = result.get("components") or []
    total = len(components)
    up_to_date = sum(1 for c in components if c.get("status") == "up_to_date")
    # No Component objects to check -- vacuously fresh, same convention
    # used below for verification_coverage.
    score = 1.0 if total == 0 else up_to_date / total
    return {"up_to_date": up_to_date, "total": total, "score": score}


async def _ttl_freshness_metric(runtime: Runtime, name: str) -> dict[str, Any]:
    result = await check_graph_freshness(runtime, {"name": name})
    fresh = result.get("fresh")
    # `fresh` is None when updated_at is missing/malformed -- treat
    # that the same as "not fresh" rather than guessing.
    score = 1.0 if fresh else 0.0
    return {"fresh": fresh, "score": score}


async def _contradictions_metric(
    runtime: Runtime, session_id: str
) -> dict[str, Any]:
    result = await detect_contradictions(runtime, {"session_id": session_id})
    count = result.get("contradiction_count", 0)
    score = 1.0 if count == 0 else 0.0
    return {"count": count, "score": score}


def _verification_coverage_metric(session: Any) -> dict[str, Any]:
    objects = getattr(session.knowledge_structure, "objects", None) or []
    records = [
        obj
        for obj in objects
        if getattr(getattr(obj, "identity", None), "type", None)
        == _VERIFICATION_RECORD_TYPE
    ]
    total = len(records)
    if total == 0:
        # No VerificationRecords to check -- vacuously fresh, same
        # convention used above for version_freshness.
        return {"fresh": 0, "total": 0, "score": 1.0}

    cutoff = datetime.now(UTC) - timedelta(seconds=_VERIFICATION_COVERAGE_TTL_SECONDS)
    fresh = 0
    for record in records:
        checked_at = _parse_checked_at(record.structure.get(_CHECKED_AT_KEY))
        if checked_at is not None and checked_at >= cutoff:
            fresh += 1

    return {"fresh": fresh, "total": total, "score": fresh / total}


async def _dead_letter_metric(runtime: Runtime, session_id: str) -> dict[str, Any]:
    result = await list_dead_lettered_conflicts(runtime, {})
    if not result.get("supported"):
        return {"count": 0, "score": 1.0}
    count = sum(
        1 for task in result.get("tasks", []) if task.get("session_id") == session_id
    )
    score = 1.0 if count == 0 else 0.5
    return {"count": count, "score": score}


def _graph_size_metric(session: Any) -> dict[str, Any]:
    structure = session.knowledge_structure
    objects = getattr(structure, "objects", None) or []
    relations = list(structure.relations()) if structure is not None else []
    return {"objects": len(objects), "relations": len(relations)}


async def check_graph_health(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    record = await runtime.storage.get_graph(name)
    if record is None:
        return {"found": False}

    session_id = record.get("session_id")
    session = runtime.get_session(session_id)
    if not session:
        # Same convention as check_component_versions: the graph is
        # registered, but its session isn't currently loaded
        # (closed/evicted) -- report this rather than raising.
        return {
            "found": True,
            "name": name,
            "session_id": session_id,
            "error": "session_not_available",
            "message": f"Session '{session_id}' for graph '{name}' is not currently loaded.",
        }

    version_freshness = await _version_freshness_metric(runtime, name)
    ttl_freshness = await _ttl_freshness_metric(runtime, name)
    contradictions = await _contradictions_metric(runtime, session_id)
    verification_coverage = _verification_coverage_metric(session)
    dead_letter = await _dead_letter_metric(runtime, session_id)
    graph_size = _graph_size_metric(session)

    health_score = (
        _WEIGHT_VERSION_FRESHNESS * version_freshness["score"]
        + _WEIGHT_TTL_FRESHNESS * ttl_freshness["score"]
        + _WEIGHT_CONTRADICTIONS * contradictions["score"]
        + _WEIGHT_VERIFICATION_COVERAGE * verification_coverage["score"]
        + _WEIGHT_DEAD_LETTER * dead_letter["score"]
    )

    return {
        "name": name,
        "session_id": session_id,
        "health_score": health_score,
        "metrics": {
            "version_freshness": version_freshness,
            "ttl_freshness": ttl_freshness,
            "contradictions": contradictions,
            "verification_coverage": verification_coverage,
            "dead_letter": dead_letter,
            "graph_size": graph_size,
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
