"""
explain_graph: generate a human-readable, plain-Markdown report of a
registered ecosystem graph (Memory Agent v1's `register_graph`), so an
LLM (or a person) can understand a graph's structure at a glance
without parsing its raw JSON knowledge structure.

Purely mechanical -- no LLM calls, no network I/O. Everything it
reports comes from `session.knowledge_structure.objects`, grouped by
`identity.type` and linked up via the same generic relation shape
`check_component_versions`/`verify_source` already use elsewhere in
this codebase: an object counts as a *relation* (an edge, not an
entity to list on its own) when its `structure` carries both
`relation_type` and `participants` (a list of the other objects'
ids), regardless of what its own `identity.type` happens to be.

Recognised entity `identity.type` values, and what each one's
`structure` is read for:

- `Component`   -- `version`, `description`
- `Module`      -- grouped under whichever `Component` it shares a
                   relation with (any `relation_type`); ungrouped
                   modules are listed separately.
- `StorageBackend` -- `label` (or `backend_type`)
- `Sweeper`     -- relations of `relation_type` "resolves" to other
                   objects are rendered as "resolves: ...".
- `Agent`       -- list-valued `structure` fields `handles`,
                   `searches`, `tools`, `resolves` (checked in that
                   order, first non-empty one wins) are rendered
                   directly, e.g. "handles: gossip, inference, ...".
                   These are read verbatim from the object -- an
                   agent's "handles"/"searches" list is usually a set
                   of concern names, not other graph objects, so
                   there is no relation to walk for it.
- `Tool`        -- grouped by `category` (default "Other").
- `ADR`         -- grouped under a `Component`, same as `Module`.
- `Plugin`      -- `status`, `description`.
- `Interface`, `Task` -- listed with `description` only; no
                   dedicated grouping (both are recognised
                   identity.type values, but neither the ecosystem's
                   own self-description graph nor this report's
                   fixed template groups them further).

Anything else is simply not shown as its own section, but is still
counted in `Total Objects`. Anomaly detection is limited to
dangling relations (a `participants` id that doesn't resolve to any
entity in the graph) -- the one issue this handler can flag without
any semantic understanding of the graph's content.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter

_COMPONENT_TYPE = "Component"
_MODULE_TYPE = "Module"
_STORAGE_BACKEND_TYPE = "StorageBackend"
_SWEEPER_TYPE = "Sweeper"
_AGENT_TYPE = "Agent"
_TOOL_TYPE = "Tool"
_ADR_TYPE = "ADR"
_PLUGIN_TYPE = "Plugin"
_INTERFACE_TYPE = "Interface"
_TASK_TYPE = "Task"

_RESOLVES_RELATION = "resolves"
_CONTRADICTS_RELATION = "contradicts"

# Checked in order on an Agent object's structure; the first non-empty
# one found is rendered. See module docstring.
_AGENT_ANNOTATION_FIELDS = ("handles", "searches", "tools", "resolves")


# ---------------------------------------------------------------------------
# Object helpers
# ---------------------------------------------------------------------------


def _obj_id(obj: Any) -> str | None:
    identity = getattr(obj, "identity", None)
    return getattr(identity, "id", None) if identity is not None else None


def _obj_type(obj: Any) -> str | None:
    identity = getattr(obj, "identity", None)
    return getattr(identity, "type", None) if identity is not None else None


def _display_name(obj: Any) -> str:
    identity = getattr(obj, "identity", None)
    name = getattr(identity, "name", None) if identity is not None else None
    return name or getattr(identity, "id", None) or "?"


def _structure(obj: Any) -> dict[str, Any]:
    return getattr(obj, "structure", None) or {}


def _is_relation(obj: Any) -> bool:
    structure = _structure(obj)
    return "relation_type" in structure and "participants" in structure


def _relation_participants(relation_obj: Any) -> list[str]:
    participants = _structure(relation_obj).get("participants") or []
    return [p for p in participants if isinstance(p, str)]


def _split_objects(objects: list[Any]) -> tuple[list[Any], list[Any]]:
    """Split `objects` into (entities, relations) -- see module docstring
    for what makes an object a relation."""
    entities: list[Any] = []
    relations: list[Any] = []
    for obj in objects:
        (relations if _is_relation(obj) else entities).append(obj)
    return entities, relations


def _group_by_type(entities: list[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for obj in entities:
        groups.setdefault(_obj_type(obj) or "Other", []).append(obj)
    return groups


def _adjacency(relations: list[Any]) -> dict[str, list[tuple[str, str]]]:
    """id -> [(other_id, relation_type), ...] across every relation object,
    undirected -- built once and reused by every section that needs to
    know what an entity is connected to."""
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for rel in relations:
        relation_type = _structure(rel).get("relation_type") or ""
        participants = _relation_participants(rel)
        for pid in participants:
            adjacency.setdefault(pid, [])
            for other in participants:
                if other != pid:
                    adjacency[pid].append((other, relation_type))
    return adjacency


def _children_by_parent(
    parents: list[Any],
    children: list[Any],
    adjacency: dict[str, list[tuple[str, str]]],
) -> tuple[dict[str, list[Any]], list[Any]]:
    """Group `children` (e.g. Module objects) under whichever `parents`
    (e.g. Component objects) they share a relation with -- any
    relation_type, since a graph's own vocabulary for "this module
    belongs to this component" isn't fixed by this handler. Returns
    (grouped, leftover): `grouped` maps a parent's id to its (sorted)
    child objects; `leftover` holds every child connected to none of
    `parents`."""
    parent_ids = {pid for pid in (_obj_id(p) for p in parents) if pid}
    grouped: dict[str, list[Any]] = {pid: [] for pid in parent_ids}
    leftover: list[Any] = []
    for child in children:
        cid = _obj_id(child)
        if cid is None:
            leftover.append(child)
            continue
        linked = {other for other, _ in adjacency.get(cid, ()) if other in parent_ids}
        if not linked:
            leftover.append(child)
            continue
        for pid in linked:
            grouped[pid].append(child)
    for pid, value in grouped.items():
        value.sort(key=_display_name)
    leftover.sort(key=_display_name)
    return grouped, leftover


# ---------------------------------------------------------------------------
# Section renderers -- each returns [] when it has nothing to show, so
# the caller can drop the section entirely (an empty graph, or one
# with no objects of that type, gets no heading for it at all).
# ---------------------------------------------------------------------------


def _render_header(name: str, record: dict[str, Any], entity_count: int, relation_count: int) -> list[str]:
    return [
        f"# Graph: {name}",
        f"**Description:** {record.get('description') or ''}",
        f"**Session ID:** {record.get('session_id') or ''}",
        f"**Last Updated:** {record.get('updated_at') or ''}",
        f"**Total Objects:** {entity_count} **Total Relations:** {relation_count}",
        "",
        "---",
    ]


def _render_components(components: list[Any]) -> list[str]:
    if not components:
        return []
    lines = ["## Components"]
    for obj in sorted(components, key=_display_name):
        structure = _structure(obj)
        bullet = f"- `{_display_name(obj)}`"
        version = structure.get("version")
        if version:
            bullet += f" (v{version})"
        description = structure.get("description")
        if description:
            bullet += f" — {description}"
        lines.append(bullet)
    return lines


def _render_grouped_by_component(
    heading: str,
    unit_label: str,
    items: list[Any],
    components: list[Any],
    adjacency: dict[str, list[tuple[str, str]]],
) -> list[str]:
    if not items:
        return []
    grouped, leftover = _children_by_parent(components, items, adjacency)
    lines = [f"## {heading}"]
    for comp in sorted(components, key=_display_name):
        comp_id = _obj_id(comp)
        if comp_id is None:
            continue
        group_items = grouped.get(comp_id, [])
        if not group_items:
            continue
        lines.append(f"### {_display_name(comp)} ({len(group_items)} {unit_label})")
        names = ", ".join(f"`{_display_name(i)}`" for i in group_items)
        lines.append(f"- {names}")
    if leftover:
        lines.append(f"### Other {heading} ({len(leftover)} {unit_label})")
        names = ", ".join(f"`{_display_name(i)}`" for i in leftover)
        lines.append(f"- {names}")
    return lines


def _render_storage_backends(backends: list[Any]) -> list[str]:
    if not backends:
        return []
    parts = []
    for obj in sorted(backends, key=_display_name):
        structure = _structure(obj)
        label = structure.get("label") or structure.get("backend_type")
        part = f"`{_display_name(obj)}`"
        if label:
            part += f" ({label})"
        parts.append(part)
    return ["## Storage Backends", "- " + ", ".join(parts)]


def _render_sweepers_with_names(
    sweepers: list[Any],
    adjacency: dict[str, list[tuple[str, str]]],
    id_to_name: dict[str, str],
) -> list[str]:
    """As `_render_sweepers`, but resolves the related ids to their
    display names via `id_to_name` (falling back to the raw id for a
    dangling reference)."""
    if not sweepers:
        return []
    lines = [f"## Sweepers ({len(sweepers)})"]
    for obj in sorted(sweepers, key=_display_name):
        oid = _obj_id(obj)
        if oid is None:
            continue
        resolves = sorted(
            {
                id_to_name.get(other_id, other_id)
                for other_id, relation_type in adjacency.get(oid, ())
                if relation_type == _RESOLVES_RELATION
            }
        )
        bullet = f"- `{_display_name(obj)}`"
        if resolves:
            bullet += " — resolves: " + ", ".join(resolves)
        lines.append(bullet)
    return lines


def _render_agents(agents: list[Any]) -> list[str]:
    if not agents:
        return []
    lines = [f"## Agents ({len(agents)})"]
    for obj in sorted(agents, key=_display_name):
        structure = _structure(obj)
        bullet = f"- `{_display_name(obj)}`"
        for field in _AGENT_ANNOTATION_FIELDS:
            values = structure.get(field)
            if not values:
                continue
            joined = ", ".join(str(v) for v in values) if isinstance(values, (list, tuple)) else str(values)
            bullet += f" — {field}: {joined}"
            break
        lines.append(bullet)
    return lines


def _render_tools(tools: list[Any]) -> list[str]:
    if not tools:
        return []
    lines = [f"## Tools ({len(tools)})"]
    by_category: dict[str, list[Any]] = {}
    for obj in tools:
        category = _structure(obj).get("category") or "Other"
        by_category.setdefault(category, []).append(obj)
    for category in sorted(by_category):
        names = ", ".join(_display_name(o) for o in sorted(by_category[category], key=_display_name))
        lines.append(f"- **{category}:** {names}")
    return lines


def _render_plugins(plugins: list[Any]) -> list[str]:
    if not plugins:
        return []
    lines = ["## Plugins"]
    for obj in sorted(plugins, key=_display_name):
        structure = _structure(obj)
        bullet = f"- `{_display_name(obj)}`"
        status = structure.get("status")
        if status:
            bullet += f" ({status})"
        description = structure.get("description")
        if description:
            bullet += f" — {description}"
        lines.append(bullet)
    return lines


def _render_simple_list(heading: str, items: list[Any]) -> list[str]:
    """Generic name (+ optional description) bullet list, used for the
    recognised identity.type values that don't otherwise have a
    dedicated section in the fixed report template (Interface, Task)."""
    if not items:
        return []
    lines = [f"## {heading}"]
    for obj in sorted(items, key=_display_name):
        description = _structure(obj).get("description")
        bullet = f"- `{_display_name(obj)}`"
        if description:
            bullet += f" — {description}"
        lines.append(bullet)
    return lines


def _render_anomalies(relations: list[Any], known_ids: set[str]) -> list[str]:
    """The one anomaly this purely-mechanical handler can detect without
    any semantic understanding of the graph's content: a relation whose
    `participants` references an id that isn't any entity in the graph."""
    dangling = set()
    for rel in relations:
        rel_id = _obj_id(rel) or "?"
        for pid in _relation_participants(rel):
            if pid not in known_ids:
                dangling.add(f"- Dangling relation `{rel_id}`: references missing object `{pid}`")
    lines = ["## Anomalies"]
    lines.extend(sorted(dangling)) if dangling else lines.append("None detected")
    return lines


def _render_summary(groups: dict[str, list[Any]], entities: list[Any], relations: list[Any]) -> list[str]:
    def count(obj_type: str) -> int:
        return len(groups.get(obj_type, []))

    contradictions = sum(
        1 for r in relations if _structure(r).get("relation_type") == _CONTRADICTS_RELATION
    )
    return [
        "## Summary",
        f"- **Components:** {count(_COMPONENT_TYPE)}",
        f"- **Modules:** {count(_MODULE_TYPE)}",
        f"- **Storage Backends:** {count(_STORAGE_BACKEND_TYPE)}",
        f"- **Sweepers:** {count(_SWEEPER_TYPE)}",
        f"- **Agents:** {count(_AGENT_TYPE)}",
        f"- **Tools:** {count(_TOOL_TYPE)}",
        f"- **ADRs:** {count(_ADR_TYPE)}",
        f"- **Plugins:** {count(_PLUGIN_TYPE)}",
        f"- **Total Objects:** {len(entities)}",
        f"- **Total Relations:** {len(relations)}",
        f"- **Contradictions:** {contradictions}",
    ]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def explain_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    record = await runtime.storage.get_graph(name)
    if record is None:
        return {"found": False}

    session_id = record.get("session_id")
    session = runtime.get_session(session_id)
    if not session:
        # Same style as check_component_versions: the graph is
        # registered, but the session it points at isn't currently
        # loaded (closed/evicted) -- report this rather than raising.
        return {
            "found": True,
            "session_id": session_id,
            "error": "session_not_available",
            "message": f"Session '{session_id}' for graph '{name}' is not currently loaded.",
        }

    objects = list(getattr(session.knowledge_structure, "objects", None) or [])
    entities, relations = _split_objects(objects)
    id_to_name = {oid: _display_name(obj) for obj in entities if (oid := _obj_id(obj))}
    known_ids = set(id_to_name)
    adjacency = _adjacency(relations)
    groups = _group_by_type(entities)

    components = groups.get(_COMPONENT_TYPE, [])

    sections = [
        _render_header(name, record, len(entities), len(relations)),
        _render_components(components),
        _render_grouped_by_component(
            "Modules", "modules", groups.get(_MODULE_TYPE, []), components, adjacency
        ),
        _render_storage_backends(groups.get(_STORAGE_BACKEND_TYPE, [])),
        _render_sweepers_with_names(groups.get(_SWEEPER_TYPE, []), adjacency, id_to_name),
        _render_agents(groups.get(_AGENT_TYPE, [])),
        _render_tools(groups.get(_TOOL_TYPE, [])),
        _render_grouped_by_component(
            "ADRs", "ADRs", groups.get(_ADR_TYPE, []), components, adjacency
        ),
        _render_plugins(groups.get(_PLUGIN_TYPE, [])),
        _render_simple_list("Interfaces", groups.get(_INTERFACE_TYPE, [])),
        _render_simple_list("Tasks", groups.get(_TASK_TYPE, [])),
        _render_anomalies(relations, known_ids),
        _render_summary(groups, entities, relations),
    ]

    report = "\n\n".join("\n".join(lines) for lines in sections if lines)

    return {
        "found": True,
        "name": name,
        "session_id": session_id,
        "report": report,
    }
