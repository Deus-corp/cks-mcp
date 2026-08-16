"""
update_graph_lifecycle: transition a registered graph's lifecycle
state (Graph Lifecycle, first slice).

Scoped to graphs already registered via ``register_graph`` -- there is
no lifecycle state for a bare, unregistered session. The allowed
transitions are intentionally restrictive for a first version: they
model a simple maturity path (draft -> published -> active, with
lateral moves to under_review/stale for graphs that need attention,
and archived as a terminal state everything can be retired to).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import graph_not_found, invalid_parameter, missing_parameter

# Every state a graph can be in. Kept in one place so schema.py's enum
# and this module's transition map can't silently drift apart.
LIFECYCLE_STATES = (
    "draft",
    "published",
    "active",
    "stale",
    "under_review",
    "archived",
)

# name -> set of states it may transition to. A state not present here
# (or mapped to an empty tuple) has no allowed outgoing transitions --
# currently just 'archived', which is treated as terminal for this
# first slice rather than allowing archived -> draft, since silently
# reviving an archived graph is easy to do by mistake and there's no
# product need for it yet. Revisit if a "restore from archive" flow is
# requested.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("published", "archived"),
    "published": ("active", "under_review", "archived"),
    "active": ("stale", "under_review", "archived"),
    "stale": ("under_review", "active", "archived"),
    "under_review": ("active", "published", "archived"),
    "archived": (),
}


async def update_graph_lifecycle(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    name = arguments.get("name")
    state = arguments.get("state")

    if not name:
        return missing_parameter("name")
    if not state:
        return missing_parameter("state")
    if state not in LIFECYCLE_STATES:
        return invalid_parameter("state", state, list(LIFECYCLE_STATES))

    record = await runtime.storage.get_graph(name)
    if record is None:
        return graph_not_found(name)

    previous_state = record.get("lifecycle_state") or "draft"

    if previous_state == state:
        # Already in the requested state -- a no-op, not an error.
        return {
            "updated": False,
            "reason": "already in requested state",
            "name": name,
            "previous_state": previous_state,
            "new_state": state,
        }

    allowed = ALLOWED_TRANSITIONS.get(previous_state, ())
    if state not in allowed:
        return {
            "error": "invalid_state_transition",
            "message": (
                f"Graph '{name}' cannot transition from '{previous_state}' "
                f"to '{state}'."
            ),
            "name": name,
            "previous_state": previous_state,
            "requested_state": state,
            "allowed": list(allowed),
        }

    # Re-register under the same name, changing only lifecycle_state.
    # register_graph's COALESCE-based upsert leaves source_graph_name
    # untouched when passed None, matching update_registered_graph's
    # existing re-register pattern.
    await runtime.storage.register_graph(
        name=name,
        session_id=record["session_id"],
        description=record.get("description", ""),
        tags=record.get("tags", ""),
        public=bool(record.get("public", False)),
        visibility=record.get("visibility"),
        team=record.get("team"),
        lifecycle_state=state,
    )

    return {
        "updated": True,
        "name": name,
        "previous_state": previous_state,
        "new_state": state,
    }
