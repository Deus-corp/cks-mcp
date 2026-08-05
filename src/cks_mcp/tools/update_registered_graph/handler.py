"""
update_registered_graph: bring a registered ecosystem graph
(``register_graph``) back in sync with the real code it describes.

Delegates the "is anything stale?" question entirely to
``check_component_versions`` (read-only) rather than re-implementing
version comparison here. When one or more ``Component`` objects are
outdated, this tool:

  1. Builds a short, factual description of each outdated component's
     new release (component name, repo, old/new version -- no network
     fetch beyond what ``check_component_versions`` already did).
  2. Passes that description to ``construct_knowledge`` so an LLM
     turns it into proper CKS objects/relations.
  3. Merges the constructed objects into the graph's existing session
     via ``evolve_knowledge`` (``add_object``/``add_relation``), and
     patches the stale ``Component`` object's own ``version`` field to
     the real, just-fetched value via ``update_object`` -- this part
     doesn't depend on the LLM output and always happens.
  4. Re-registers the (now-updated) session under the same name via
     ``register_graph``.

Deliberately NOT implemented: cloning component repositories with
``git`` (or any other shell-out) and running/importing code from them.
Nothing in this codebase does that anywhere, and doing it here would
mean an MCP tool call resolves an untrusted, LLM/graph-controlled
string (a component's ``repo_url``) into an arbitrary ``git clone``
target and then executes discovery logic against whatever that
repository contains -- a supply-chain/RCE surface this server
otherwise takes care to avoid (see ``verify_source``'s SSRF
protections, and ``check_component_versions`` fetching only a single
well-known file over the read-only GitHub raw API). Rebuilding graph
*content* from a component update only needs a description of what
changed, not the component's actual source tree.

If nothing is outdated, this is a no-op. If something is outdated but
no LLM provider is configured for ``construct_knowledge``, nothing is
changed and ``{"error": "LLM provider required"}`` is returned.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter
from cks_mcp.tools.check_component_versions.handler import check_component_versions
from cks_mcp.tools.construct_knowledge.handler import construct_knowledge
from cks_mcp.tools.evolve.handler import evolve_knowledge
from cks_mcp.tools.register_graph.handler import register_graph

_NO_PROVIDER_MARKER = "No LLM provider available"


def _describe_update(component: dict[str, Any]) -> str:
    name = component["component"]
    old = component.get("graph_version")
    new = component.get("actual_version")
    return (
        f"The component '{name}' was updated from version {old} to "
        f"version {new}. Describe this release as a knowledge object "
        f"for '{name}' capturing its new version."
    )


def _find_component_object_id(session: Any, component_name: str) -> str | None:
    """Locate the Component object's own id, matching the same lookup
    check_component_versions uses (identity.name, falling back to
    identity.id), so the version patch lands on the right object."""
    for obj in session.knowledge_structure.objects:
        identity = getattr(obj, "identity", None)
        if identity is None or getattr(identity, "type", None) != "Component":
            continue
        if (getattr(identity, "name", None) or identity.id) == component_name:
            return identity.id
    return None


def _operations_from_constructed(serialized: str) -> list[dict[str, Any]]:
    """Turn construct_knowledge's serialized CKS JSON into a list of
    evolve_knowledge operations that add every object/relation it
    contains to the target session."""
    data = json.loads(serialized)
    operations: list[dict[str, Any]] = []
    for obj in data.get("objects", []):
        structure = dict(obj.get("structure") or {})
        if "participants" in structure and "relation_type" in structure:
            participants = structure.pop("participants")
            relation_type = structure.pop("relation_type")
            operations.append(
                {
                    "type": "add_relation",
                    "identity": obj["identity"],
                    "participants": participants,
                    "relation_type": relation_type,
                    "structure": structure,
                }
            )
        else:
            operations.append(
                {
                    "type": "add_object",
                    "identity": obj["identity"],
                    "structure": structure,
                }
            )
    return operations


async def update_registered_graph(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    check_result = await check_component_versions(runtime, {"name": name})

    if not check_result.get("found"):
        return {"found": False}
    if "error" in check_result:
        # e.g. session_not_available -- nothing safe to update.
        return check_result

    outdated = [
        c for c in check_result.get("components", []) if c.get("status") == "outdated"
    ]
    if not outdated:
        return {"updated": False, "reason": "already current"}

    record = await runtime.storage.get_graph(name)
    session_id = record.get("session_id")

    updated_components: list[str] = []

    for component in outdated:
        component_name = component["component"]

        constructed = await construct_knowledge(
            runtime,
            {
                "text": _describe_update(component),
                "hint": f"new release of component '{component_name}'",
            },
        )
        if constructed.get("error") == "internal_error" and _NO_PROVIDER_MARKER in constructed.get(
            "message", ""
        ):
            # Nothing has been modified yet -- safe to stop here rather
            # than leave the graph partially updated.
            return {"error": "LLM provider required"}
        if "error" in constructed:
            return {
                "error": "construct_knowledge_failed",
                "component": component_name,
                "details": constructed,
            }

        session = runtime.get_session(session_id)
        if session is None:
            return {
                "error": "session_not_available",
                "message": f"Session '{session_id}' for graph '{name}' is not currently loaded.",
            }

        operations = _operations_from_constructed(constructed["serialized"])

        object_id = _find_component_object_id(session, component_name)
        if object_id is not None:
            operations.append(
                {
                    "type": "update_object",
                    "object_id": object_id,
                    "structure_patch": {"version": component.get("actual_version")},
                }
            )

        evolve_result = await evolve_knowledge(
            runtime, {"session_id": session_id, "operations": operations}
        )
        if "error" in evolve_result:
            return {
                "error": "evolve_failed",
                "component": component_name,
                "details": evolve_result,
            }

        session_id = evolve_result["session_id"]
        updated_components.append(component_name)

    register_result = await register_graph(
        runtime,
        {
            "name": name,
            "session_id": session_id,
            "description": record.get("description", ""),
            "tags": record.get("tags", ""),
            "public": bool(record.get("public", False)),
        },
    )
    if "error" in register_result:
        return register_result

    return {"updated": True, "components_updated": updated_components}
