"""
CKS MCP — Conflict Inbox.

``GossipAdapter`` (cks-runtime, ADR-008) escalates an unresolvable
gossip merge by publishing ``GossipConflictDetected`` on the Runtime
``EventBus`` instead of raising synchronously -- a background gossip
cycle has no caller waiting on the call. Nothing previously consumed
that event: it was logged (see ``observability.py``'s general
``RuntimeEvent`` handling, which did *not* subscribe to it) and then
lost.

This module gives an external Critic agent -- a separate MCP client
session that decides how to resolve conflicts -- something to poll:
a small in-memory queue, filled by a subscriber ``gossip.py`` wires up
only when gossip is enabled (the event never fires otherwise), and
drained through the ``list_gossip_conflicts`` tool. A conflict record
carries ``session_id`` (the target to resolve), ``source_replica_id``,
the conflicting identity ids, and (ADR-008 status update)
``source_session_id`` -- a real local session cks-runtime's
``GossipAdapter`` registered at the moment of conflict, holding the
remote replica's content that failed to merge. Before that field
existed, a record was only ever a bare list of conflicting ids with no
way to see what the remote side actually contained; now the agent can
call ``merge_branch`` with ``target_session_id=session_id,
source_session_id=source_session_id`` directly to get back the
structured per-object diff (``object_id``/``target_diff``/
``source_diff``) and resolve it the same way any other branch conflict
is resolved. ``source_session_id`` is empty when a record predates this
field, or when registering the branch itself failed -- treat that as
"no diff available, only the conflicting ids above".

``InferenceStalenessSweeper`` (cks-runtime, ADR-009) escalates the same
way, for a different kind of finding: publishing
``InferenceConflictDetected`` when a background sweep turns up a
reasoning-staleness diagnostic (``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT``
/ ``CKS-EXT-STALE-PREMISE``) nobody has looked at yet. ADR-009 itself
notes this consumer as unblocked-but-undecided; this module is that
decision. Kept in a *separate* queue from the gossip one rather than
folded into the same record shape -- ADR-009 is explicit that this is
not ``GossipConflictDetected`` repurposed (a single-structure belief
conflict has no ``source_replica_id``/``source_session_id`` to speak
of), and unlike a gossip conflict there is no single ``conclusion_id``
to hand a caller: ``CKS-EXT-STALE-PREMISE`` findings are keyed by
InferenceStep id, not by conclusion, so extracting one field to act on
would silently drop that case. Drained through
``list_inference_conflicts``, mirroring ``list_gossip_conflicts``'
peek/drain/session_id-filter shape; a Critic agent reads each finding's
``message`` to work out the ``conclusion_id`` (present in the
confidence-conflict message text) to hand ``arbitrate_inference_conflict``,
the same way it already reasons over free-text diagnostics elsewhere.

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

from cks_runtime.events.runtime_event import (
    CRDTForkDetected,
    GossipConflictDetected,
    InferenceConflictDetected,
)

# Type alias for the record-list return shape, defined at module scope
# rather than referenced as bare `list[...]` inside ConflictInbox: the
# class defines a method literally named `list`, which shadows the
# builtin `list` for any type annotation written later in the same
# class body (mypy resolves annotations against the enclosing scope at
# that point in the class body, same as plain Python name resolution).
_Records = list[dict[str, Any]]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ConflictRecord:
    record_id: str
    detected_at: float
    source_replica_id: str
    session_id: str
    source_session_id: str = ""
    conflicts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "detected_at": self.detected_at,
            "source_replica_id": self.source_replica_id,
            "session_id": self.session_id,
            "source_session_id": self.source_session_id,
            "conflicts": list(self.conflicts),
        }


@dataclass(slots=True)
class _InferenceConflictRecord:
    record_id: str
    detected_at: float
    session_id: str
    version_id: str
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "detected_at": self.detected_at,
            "session_id": self.session_id,
            "version_id": self.version_id,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(slots=True)
class _CRDTForkRecord:
    """
    ADR-013 Stage 2: a buffered ``CRDTForkDetected`` event -- an
    MV-Register pointer with two or more concurrent (causally
    unordered) object_ids. ``event_id`` is the
    ``cks_conflict_events.event_id`` the fork is persisted under (see
    ``CRDTStore.escalate_fork``), so a Critic agent can resolve it via
    ``CRDTStore.resolve_pointer`` + ``mark_fork_resolved`` without a
    separate lookup.
    """

    record_id: str
    detected_at: float
    pointer_key: str
    event_id: str
    conflicting_object_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "detected_at": self.detected_at,
            "pointer_key": self.pointer_key,
            "event_id": self.event_id,
            "conflicting_object_ids": list(self.conflicting_object_ids),
        }


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


class ConflictInbox:
    """
    Process-level in-memory queues of unresolved conflicts: gossip merge
    conflicts (``GossipConflictDetected``) and reasoning-staleness
    findings (``InferenceConflictDetected``), kept as two separate lists
    behind one process-level object since both are "things a Critic
    agent should look at", but shaped too differently (see module
    docstring) to share one record type.

    Each ring buffer is capped at ``max_records`` (oldest evicted first)
    so a Critic agent that never polls can't grow this unboundedly --
    the same trade-off ``ToolTelemetry`` makes for call history.
    """

    def __init__(self, max_records: int = 1_000) -> None:
        self._records: list[_ConflictRecord] = []
        self._inference_records: list[_InferenceConflictRecord] = []
        self._crdt_fork_records: list[_CRDTForkRecord] = []
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
            source_session_id=event.source_session_id,
            conflicts=[str(c) for c in event.conflicts],
        )
        async with self._get_lock():
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records :]

    async def record_inference(self, event: InferenceConflictDetected) -> None:
        """Buffer an ``InferenceConflictDetected`` event; evict oldest over budget."""
        entry = _InferenceConflictRecord(
            record_id=str(uuid4()),
            detected_at=time.time(),
            session_id=event.session_id,
            version_id=event.version_id,
            diagnostics=[dict(d) for d in event.diagnostics],
        )
        async with self._get_lock():
            self._inference_records.append(entry)
            if len(self._inference_records) > self._max_records:
                self._inference_records = self._inference_records[-self._max_records :]

    async def record_crdt_fork(self, event: CRDTForkDetected) -> None:
        """Buffer a ``CRDTForkDetected`` event (ADR-013 Stage 2); evict oldest over budget."""
        entry = _CRDTForkRecord(
            record_id=str(uuid4()),
            detected_at=time.time(),
            pointer_key=event.pointer_key,
            event_id=event.conflict_event_id,
            conflicting_object_ids=[str(o) for o in event.conflicting_object_ids],
        )
        async with self._get_lock():
            self._crdt_fork_records.append(entry)
            if len(self._crdt_fork_records) > self._max_records:
                self._crdt_fork_records = self._crdt_fork_records[-self._max_records :]

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def list(
        self,
        *,
        session_id: str | None = None,
        drain: bool = True,
    ) -> _Records:
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

    async def list_inference(
        self,
        *,
        session_id: str | None = None,
        drain: bool = True,
    ) -> _Records:
        """
        Return buffered inference-staleness findings, oldest first.

        Same ``session_id``/``drain`` semantics as ``list`` above, over
        the separate inference-conflict queue.
        """
        async with self._get_lock():
            if session_id is None:
                matched_inf = list(self._inference_records)
                if drain:
                    self._inference_records.clear()
            else:
                matched_inf = [r for r in self._inference_records if r.session_id == session_id]
                if drain:
                    self._inference_records = [
                        r for r in self._inference_records if r.session_id != session_id
                    ]

        return [r.as_dict() for r in matched_inf]

    async def list_crdt_forks(
        self,
        *,
        pointer_key: str | None = None,
        drain: bool = True,
    ) -> _Records:
        """
        Return buffered MV-Register fork records (ADR-013 Stage 2),
        oldest first. Same ``drain`` semantics as ``list``/
        ``list_inference`` above, filtered by ``pointer_key`` instead
        of ``session_id`` -- a CRDT fork has no session, only a
        pointer.
        """
        async with self._get_lock():
            if pointer_key is None:
                matched_fork = list(self._crdt_fork_records)
                if drain:
                    self._crdt_fork_records.clear()
            else:
                matched_fork = [
                    r for r in self._crdt_fork_records if r.pointer_key == pointer_key
                ]
                if drain:
                    self._crdt_fork_records = [
                        r for r in self._crdt_fork_records if r.pointer_key != pointer_key
                    ]

        return [r.as_dict() for r in matched_fork]

    async def reset(self) -> None:
        """Clear all buffered records (gossip, inference, and CRDT-fork conflicts)."""
        async with self._get_lock():
            self._records.clear()
            self._inference_records.clear()
            self._crdt_fork_records.clear()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

conflict_inbox = ConflictInbox()

__all__ = ["ConflictInbox", "conflict_inbox"]