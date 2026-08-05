"""
check_graph_freshness: read-only check of whether a registered graph
(Memory Agent v1's ``register_graph``) is still fresh, using the same
TTL ``GraphFreshnessSweeper`` (Memory Agent v2, cks-runtime) applies in
the background. Does not refresh the graph itself -- that stays with a
future update agent, consistent with GraphFreshnessSweeper's own
detection-only design.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter

_SECONDS_PER_DAY = 24 * 3600


def _parse_updated_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def check_graph_freshness(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    record = await runtime.storage.get_graph(name)
    if record is None:
        return {"found": False}

    ttl_seconds = runtime.config.graph_freshness_ttl_seconds
    ttl_days = ttl_seconds / _SECONDS_PER_DAY

    updated_at_raw = record.get("updated_at")
    updated_at = _parse_updated_at(updated_at_raw)
    if updated_at is None:
        # Same as GraphFreshnessSweeper: an unparsable/missing
        # updated_at can't be judged fresh or stale -- report the raw
        # value rather than guessing.
        return {
            "fresh": None,
            "last_updated": updated_at_raw,
            "ttl_days": ttl_days,
        }

    age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    fresh = age_seconds < ttl_seconds

    if fresh:
        return {"fresh": True}

    return {
        "fresh": False,
        "last_updated": updated_at_raw,
        "ttl_days": ttl_days,
    }
