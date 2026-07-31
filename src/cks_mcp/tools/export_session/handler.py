"""
export_session: export a full session bundle for migration or archival.

Unlike ``export_knowledge`` — which converts the *current* Knowledge Structure
to an external format (JSON-LD, Turtle, RDF/XML) — ``export_session`` packages
everything you need to reconstruct a session in another runtime instance:

  * The current (latest) Knowledge Structure in canonical CKS JSON.
  * The complete version history (metadata only; structures/patches are
    included only when ``include_structures`` is True to keep the payload
    manageable for long sessions).
  * Session metadata (session_id, parent_session_id, parent_version_id, ...).

The output is a self-contained JSON document.  Consumers can import it with
``validate_knowledge`` (using the embedded ``cks_json``) and replay individual
versions if they need the full history.

``format`` controls the envelope:
  * ``"bundle"`` (default) — a single JSON object with a ``cks_mcp_export``
    wrapper, a schema version stamp, and all fields described above.  Safe to
    pass back to the server without further processing.
  * ``"cks"``  — bare canonical CKS JSON of the *current* structure only
    (identical to what ``serialize_knowledge`` returns).  Useful when you only
    need the latest state for import into another tool.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found

# Bump this when the bundle schema changes in a breaking way.
_BUNDLE_SCHEMA_VERSION = "1.0"


async def export_session(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    """MCP tool handler for export_session."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    fmt = (arguments.get("format") or "bundle").lower()
    include_structures = bool(arguments.get("include_structures", False))

    structure = session.knowledge_structure
    cks_json: str = runtime.core_bridge.serialize(structure)

    # ------------------------------------------------------------------ #
    # Bare CKS format — current structure only                            #
    # ------------------------------------------------------------------ #
    if fmt == "cks":
        return {
            "format": "cks",
            "session_id": session_id,
            "cks_json": cks_json,
        }

    # ------------------------------------------------------------------ #
    # Bundle format — full migration envelope                             #
    # ------------------------------------------------------------------ #
    if fmt != "bundle":
        return {
            "error": "unsupported_format",
            "message": (
                f"Format '{fmt}' is not supported. "
                "Use 'bundle' (default) or 'cks'."
            ),
        }

    # Build version history summary.
    version_history: list[dict[str, Any]] = []
    for ver in session.version_history:
        entry: dict[str, Any] = {
            "version_id": ver.version_id,
            "transaction_id": ver.transaction_id,
            "created_at": ver.created_at.isoformat(),
            "state_hash": ver.state_hash,
        }
        if include_structures and ver.knowledge_structure is not None:
            try:
                entry["cks_json"] = runtime.core_bridge.serialize(
                    ver.knowledge_structure
                )
            except Exception:
                entry["cks_json"] = None
        version_history.append(entry)

    bundle: dict[str, Any] = {
        "cks_mcp_export": True,
        "schema_version": _BUNDLE_SCHEMA_VERSION,
        "session": {
            "session_id": session.session_id,
            "parent_session_id": session.parent_session_id,
            "parent_version_id": session.parent_version_id,
            "closed": session.closed,
            "metadata": dict(session.metadata),
        },
        "current_structure": {
            "root_hash": structure.root_hash,
            "objects_count": len(structure.objects),
            "relations_count": len(structure.relations()),
            "cks_json": cks_json,
        },
        "version_history": {
            "count": len(version_history),
            "include_structures": include_structures,
            "versions": version_history,
        },
    }

    return {
        "format": "bundle",
        "session_id": session_id,
        "bundle": bundle,
        # Convenience: the raw JSON string so callers can write it to disk
        # directly without a second serialisation step.
        "bundle_json": json.dumps(bundle, ensure_ascii=False),
    }
