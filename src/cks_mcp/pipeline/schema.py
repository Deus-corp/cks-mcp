"""
ADR-007 pipeline schema helpers.

Every object flowing through the Researcher -> Reviewer -> Synthesizer
-> Arbiter pipeline carries two payload-level (``structure``) fields,
per ADR-007 Decision 1 and Decision 4:

- ``current_status`` -- one of the ``PipelineStatus`` values below.
  This is a *cache*, derived from ``transition_log``, kept as a plain
  field so it stays cheaply queryable (``structure_filters`` on
  ``query_subgraph``, or a SQL ``WHERE`` clause on a future Postgres
  claim query per Decision 2) without replaying the whole log.
- ``transition_log`` -- an **append-only** list of
  ``{"timestamp", "agent", "action", "transitioned_to",
  "reasoning_node_id"?}`` entries. Nothing overwrites or removes an
  entry; each step only ever appends. This is the source of truth
  ``current_status`` is derived from.

Full reasoning content (a Reviewer's rationale, an Arbiter's
validation notes, ...) is **not** inlined into a transition_log entry
-- it is written as its own graph node (e.g. a ``ReasoningNode``) and
linked in, with only that node's id referenced from
``reasoning_node_id`` (ADR-007 Decision 4). These helpers only ever
prepare ``evolve_knowledge`` operation descriptors; they never mutate
a session's objects directly, so every transition goes through the
normal commit/provenance/validation path in ``evolve_knowledge``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class PipelineStatus:
    """``current_status`` values used by the Milestone 1 pipeline.

    Only ``AWAITING_RESEARCH``/``AWAITING_REVIEW``/``RESOLVED``/
    ``NEEDS_RESEARCH`` are driven by Milestone 1 (Researcher +
    Reviewer). ``AWAITING_SYNTHESIS``/``AWAITING_ARBITRATION`` are
    reserved here so Milestone 2 (Synthesizer + Arbiter) doesn't need
    a schema migration to add them.
    """

    AWAITING_RESEARCH = "awaiting_research"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_SYNTHESIS = "awaiting_synthesis"
    AWAITING_ARBITRATION = "awaiting_arbitration"
    NEEDS_RESEARCH = "needs_research"
    RESOLVED = "resolved"


@dataclass(slots=True, frozen=True)
class TransitionEntry:
    """One append-only ``transition_log`` entry."""

    agent: str
    action: str
    transitioned_to: str
    reasoning_node_id: str | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
            "agent": self.agent,
            "action": self.action,
            "transitioned_to": self.transitioned_to,
            "reasoning_node_id": self.reasoning_node_id,
        }


def _thaw(value: Any) -> Any:
    """Recursively convert cks-core's frozen ``MappingProxyType``/tuple
    structure representation back into plain ``dict``/``list`` so a
    ``transition_log`` read off a committed object can be safely
    re-embedded (and later ``json.dumps``'d by storage) inside a new
    ``evolve_knowledge`` operation without an "Object of type
    mappingproxy is not JSON serializable" surprise at commit time."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def read_status(obj: Any) -> str | None:
    """Read ``current_status`` off a ``KnowledgeObject``-like value.

    Accepts either a live object (``obj.structure`` dict-like) or a
    plain ``dict`` (e.g. from a serialized structure / query_subgraph
    result), so callers don't need to know which shape they hold.
    """
    structure = obj.structure if hasattr(obj, "structure") else obj.get("structure", obj)
    return structure.get("current_status") if structure else None


def read_transition_log(obj: Any) -> list[dict[str, Any]]:
    """Read ``transition_log`` off a ``KnowledgeObject``-like value,
    thawed into plain ``dict``/``list`` (see ``_thaw``) so callers can
    safely feed it straight back into a new ``evolve_knowledge``
    operation."""
    structure = obj.structure if hasattr(obj, "structure") else obj.get("structure", obj)
    return _thaw(list(structure.get("transition_log") or [])) if structure else []


def has_agent_transitioned(
    obj: Any, agent: str, *, content_hash: str | None = None
) -> bool:
    """
    Idempotency check (ADR-007 Decision 4 / the ``AgentStep.run``
    docstring in the Minimal API): has ``agent`` already recorded a
    transition for this object?

    When ``content_hash`` is given, only an entry whose own
    ``content_hash`` matches counts -- this is what lets a step safely
    re-run after the *content* of an object changes underneath a prior
    verdict, while still skipping a redundant LLM call against
    unchanged content.
    """
    for entry in read_transition_log(obj):
        if entry.get("agent") != agent:
            continue
        if content_hash is not None and entry.get("content_hash") != content_hash:
            continue
        return True
    return False


def append_transition(
    object_id: str,
    *,
    agent: str,
    action: str,
    transitioned_to: str,
    current_log: list[dict[str, Any]] | None = None,
    reasoning_node_id: str | None = None,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """
    Build an ``evolve_knowledge`` ``update_object`` operation that
    appends one entry to ``transition_log`` and refreshes the
    ``current_status`` cache -- never a raw mutation of the object.

    ``current_log`` should be the transition_log *as read just before
    this call* (via ``read_transition_log``); the new entry is
    appended to a copy of it so the operation's ``structure_patch``
    carries the full log (this pipeline's ``transition_log`` field is
    plain last-write-wins under CRDT merge for Milestone 1's
    single-backend scope -- see ADR-007 Decision 2 -- so the patch
    must include prior entries, not just the new one).
    """
    entry = TransitionEntry(
        agent=agent,
        action=action,
        transitioned_to=transitioned_to,
        reasoning_node_id=reasoning_node_id,
    ).to_dict()
    if content_hash is not None:
        entry["content_hash"] = content_hash

    new_log = [*(current_log or []), entry]

    return {
        "type": "update_object",
        "object_id": object_id,
        "structure_patch": {
            "current_status": transitioned_to,
            "transition_log": new_log,
        },
        "mode": "merge",
    }