"""
list_gossip_conflicts: drain (or peek) the queue of gossip merge
conflicts escalated by ``GossipAdapter`` (cks-runtime, ADR-008) that
no one has resolved yet.

This is a read on ``conflict_inbox`` (see ``cks_mcp.conflict_inbox``),
not on the Runtime -- ``session_id`` is a filter, not a session this
tool operates against, so unlike most other tools here it takes no
``runtime`` state into account and never requires an existing session.
Each returned record's ``source_session_id`` (ADR-008 status update)
is already a real session on this Runtime -- no extra lookup needed
before passing it straight to ``merge_branch``.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.conflict_inbox import conflict_inbox


async def list_gossip_conflicts(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return buffered gossip conflicts, draining them unless peek=true."""
    session_id = arguments.get("session_id")
    peek = bool(arguments.get("peek", False))

    conflicts = await conflict_inbox.list(session_id=session_id, drain=not peek)

    return {"conflicts": conflicts, "count": len(conflicts)}
