"""
CKS MCP — Gossip Conflict Inbox.

``GossipAdapter`` (cks-runtime, ADR-008) escalates an unresolvable
gossip merge by publishing ``GossipConflictDetected`` on the Runtime
``EventBus`` instead of raising synchronously -- a background gossip
cycle has no caller waiting on the call. Nothing previously consumed
that event: it was logged (see ``observability.py``'s general
``RuntimeEvent`` handling, which does *not* currently subscribe to
it) and then lost.

This module gives an external Critic agent -- a separate MCP client
session that decides how to resolve conflicts -- something to poll:
a small in-memory queue, filled by a subscriber ``gossip.py`` wires up
only when gossip is enabled (the event never fires otherwise), and
drained through the ``list_gossip_conflicts`` tool. A conflict record
carries just enough to act on it: ``session_id`` (which ``merge_branch``
call this is), ``source_replica_id``, and the conflicting identity ids
-- the agent is expected to follow up with ``compare_versions``/
``explain_diff`` for the structured diff and ``merge_branch`` to
commit the resolution, the same as any human-driven conflict
resolution would.

Kept separate from ``telemetry.py``: that module aggregates completed
tool calls for dashboards; this one queues open work items awaiting
action, and reads are destructive (draining) by default rather than
cumulative snapshots.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from cks_runtime.events.runtime_event import GossipConflictDetected

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ConflictRecord:
    record_id: str
    detected_at: float
    source_replica_id: str
    session_id: str
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "detected_at": self.detected_at,
            "source_replica_id": self.source_replica_id,
            "session_id": self.session_id,
            "conflicts": list(self.conflicts),
        }


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


class ConflictInbox:
    """
    Process-level in-memory queue of unresolved gossip conflicts.

    The ring buffer is capped at ``max_records`` (oldest evicted first)
    so a Critic agent that never polls can't grow this unboundedly --
    the same trade-off ``ToolTelemetry`` makes for call history.
    """

    def __init__(self, max_records: int = 1_000) -> None:
        self._records: list[_ConflictRecord] = []
        self._lock: asyncio.Lock | None = None  # created lazily inside event loop
        self._max_records = max_records

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def record(self, event: GossipConflictDetected) -> None:
        """Buffer a ``GossipConflictDetected`` event; evict oldest over budget."""
        entry = _ConflictRecord(
            record_id=str(uuid4()),
            detected_at=time.time(),
            source_replica_id=event.source_replica_id,
            session_id=event.session_id,
            conflicts=[str(c) for c in event.conflicts],
        )
        async with self._get_lock():
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records :]

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def list(
        self,
        *,
        session_id: str | None = None,
        drain: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Return buffered conflict records, oldest first.

        ``session_id`` filters to that session only. ``drain`` (default
        ``True``) removes the returned records from the inbox -- a
        Critic agent that just read a conflict is expected to act on
        it, and re-serving it on every subsequent poll would make
        "how many conflicts are outstanding" impossible to answer
        cumulatively. Pass ``drain=False`` to peek without consuming.
        """
        async with self._get_lock():
            if session_id is None:
                matched = list(self._records)
                if drain:
                    self._records.clear()
            else:
                matched = [r for r in self._records if r.session_id == session_id]
                if drain:
                    self._records = [r for r in self._records if r.session_id != session_id]

        return [r.as_dict() for r in matched]

    async def reset(self) -> None:
        """Clear all buffered records."""
        async with self._get_lock():
            self._records.clear()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

conflict_inbox = ConflictInbox()

__all__ = ["ConflictInbox", "conflict_inbox"]
