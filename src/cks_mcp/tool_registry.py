"""
CKS MCP Tool Registry — JSON schemas and handler bindings for all 18 tools.

This module exists solely to keep the tool definitions out of server.py,
which remains responsible only for JSON-RPC transport. Adding a new tool
now touches exactly two places: its own handler module (in tools/) and
the TOOLS dict below.
"""

from __future__ import annotations

from cks_mcp.observability import log_tool_call
from cks_mcp.tools import (
    validate_knowledge,
    serialize_knowledge,
    explain_knowledge,
    evolve_knowledge,
)
from cks_mcp.tools.verify_source import verify_source
from cks_mcp.tools.revert import list_versions, revert_version
from cks_mcp.tools.compare import compare_versions
from cks_mcp.tools.merge import merge_knowledge, merge_branch
from cks_mcp.tools.branch import create_branch, close_session
from cks_mcp.tools.query_subgraph import query_subgraph_tool
from cks_mcp.tools.search_semantic import search_semantic
from cks_mcp.tools.get_metrics import get_metrics
from cks_mcp.tools.visualize_graph import visualize_graph
from cks_mcp.tools.explain_diff import explain_diff
from cks_mcp.tools.suggest_evolution import suggest_evolution

# ---------------------------------------------------------------------------
# Shared parameter descriptions
# ---------------------------------------------------------------------------

JSON_DATA_DESCRIPTION = (
    "A valid CKS Knowledge Structure as a JSON string. Each object has "
    "an 'identity' ({'id', 'type', 'name'}) and a free-form 'structure' "
    "dict. Relations are objects whose 'structure' contains "
    "'participants' (a list of object ids) and 'relation_type'. Example: "
    '\'{"objects": [{"identity": {"id": "obj-1", "type": "Definition", '
    '"name": "Photosynthesis"}, "structure": {"content": "..."}}, '
    '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, '
    '"structure": {"participants": ["obj-1", "obj-2"], "relation_type": '
    '\'derives"}}]}\'.'
)

TOOLS = {
    "validate_knowledge": {
        "name": "validate_knowledge",
        "description": (
            "Validate a Canonical Knowledge Structure. Returns validation result and diagnostics. "
            "Optionally accepts 'session_id' to validate an existing session's current state instead "
            "of creating a new one. Optionally accepts 'extensions' to opt into additional, non-default "
            "validation rules for this call only (see 'extensions' parameter). "
            "Returns a 'session_id' that can be used with list_versions and revert_version to track and manage version history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, validate the current structure of this session "
                        "instead of creating a new session from json_data."
                    ),
                },
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of opt-in validation extensions to apply for this call "
                        "only (does not affect other calls). Currently available: "
                        "'embedding_projection', 'verification_record', 'type_hierarchy', "
                        "'relation_type'. "
                        "Example of a correct EmbeddingProjection with its 'represents' relation: "
                        '{"objects": ['
                        '{"identity": {"id": "src-1", "type": "Document", "name": "Real paper"}, "structure": {}}, '
                        '{"identity": {"id": "proj-1", "type": "EmbeddingProjection", "name": "projection"}, "structure": {"store_ref": "vecdb://xyz"}}, '
                        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["src-1", "proj-1"], "relation_type": "represents"}}'
                        ']}.'
                        " Example of TypeDefinition and TypeRule for ontology validation: "
                        '{"objects": ['
                        '{"identity": {"id": "td-1", "type": "TypeDefinition", "name": "Planet"}, "structure": {"type_name": "Planet", "parent_type": "CelestialBody"}}, '
                        '{"identity": {"id": "tr-1", "type": "TypeRule", "name": "orbits rule"}, "structure": {"relation_type": "orbits", "allowed_source_types": ["Planet", "Moon"], "allowed_target_types": ["Star", "Planet"]}}'
                        ']}.'
                    ),
                },
            },
            "required": ["json_data"],
        },
        "handler": log_tool_call("validate_knowledge")(validate_knowledge),
    },
    "serialize_knowledge": {
        "name": "serialize_knowledge",
        "description": (
            "Serialize a Knowledge Structure into its canonical JSON representation. "
            "Optionally accepts 'session_id' to serialize the current state of an existing session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, serialize the current structure of this session "
                        "instead of creating a new session from json_data."
                    ),
                },
            },
            "required": ["json_data"],
        },
        "handler": log_tool_call("serialize_knowledge")(serialize_knowledge),
    },
    "explain_knowledge": {
        "name": "explain_knowledge",
        "description": (
            "Produce a human-readable explanation of a Knowledge Structure. "
            "Optionally accepts 'session_id' to explain the current state of an existing session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, explain the current structure of this session "
                        "instead of creating a new session from json_data."
                    ),
                },
            },
            "required": ["json_data"],
        },
        "handler": log_tool_call("explain_knowledge")(explain_knowledge),
    },
    "evolve_knowledge": {
        "name": "evolve_knowledge",
        "description": (
            "Apply structural evolution operators to a Knowledge Structure. "
            "Returns a new 'session_id' and 'version_id'. The 'session_id' can be used with list_versions and revert_version."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "operations": {
                    "type": "array",
                    "description": (
                        "List of evolution operators to apply, in order. Each operator is an "
                        "object with a 'type' field; the other required fields depend on that "
                        "type and are NOT interchangeable between operators:\n"
                        "  - 'add_object': requires 'identity' ({'id','type','name'}) and "
                        "optional 'structure' (a free-form dict). Fails if the id already "
                        "exists -- use 'update_object' to change an existing object instead.\n"
                        "  - 'add_relation': requires 'identity', 'participants' (list of "
                        "existing object ids), 'relation_type', and optional 'structure'.\n"
                        "  - 'remove_object': requires 'object_id' (NOT 'identity'). Removing "
                        "an object also cascade-removes every relation that references it; "
                        "the response's 'cascade_removed_relations' lists what was removed.\n"
                        "  - 'remove_relation': requires 'relation_id' (NOT 'identity'). Only "
                        "valid for an id that is actually a relation -- use 'remove_object' "
                        "for a plain object.\n"
                        "  - 'update_object': requires 'object_id' and 'structure_patch' (a "
                        "dict of fields to change), and optional 'mode' ('merge', the default "
                        "-- shallow-merges structure_patch into the existing structure, and a "
                        "patch value of null deletes that key -- or 'replace', which replaces "
                        "the whole structure dict). Use this instead of remove_object + "
                        "add_object to change an object's content: the object's id and every "
                        "relation referencing it are left untouched, with no cascade.\n"
                        "Example: "
                        '\'[{"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", '
                        '"name": "New"}, "structure": {}}, {"type": "add_relation", "identity": '
                        '{"id": "rel-1", "type": "Relation", "name": "r"}, "participants": '
                        '["obj-1", "obj-2"], "relation_type": "derives"}, {"type": '
                        '"update_object", "object_id": "obj-1", "structure_patch": '
                        '{"summary": "revised text"}}]\'.'
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, evolve the current structure of this session "
                        "instead of creating a new session from json_data."
                    )
                },
            },
            "required": ["json_data"],
        },
        "handler": log_tool_call("evolve_knowledge")(evolve_knowledge),
    },
    "merge_knowledge": {
        "name": "merge_knowledge",
        "description": (
            "Three-way merge of Knowledge Structures. Provide a common ancestor "
            "(base) and two independently evolved branches. Returns the merged "
            "structure or a list of conflicts if automatic resolution is impossible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data_base": {
                    "type": "string",
                    "description": "The common ancestor Knowledge Structure as a JSON string.",
                },
                "json_data_branch_a": {
                    "type": "string",
                    "description": "Branch A Knowledge Structure as a JSON string.",
                },
                "json_data_branch_b": {
                    "type": "string",
                    "description": "Branch B Knowledge Structure as a JSON string.",
                },
                "resolutions": {
                    "type": "object",
                    "description": "Optional. Per-object conflict resolution strategy. Keys are object IDs. Values: 'branch_a', 'branch_b', null (drop), or a full object definition to override the conflict."
                }
            },
            "required": ["json_data_base", "json_data_branch_a", "json_data_branch_b"],
        },
        "handler": log_tool_call("merge_knowledge")(merge_knowledge),
    },
    "create_branch": {
        "name": "create_branch",
        "description": (
            "Fork a new session from an existing one. Use this to isolate an "
            "experiment, explore an alternative modeling approach, or try a "
            "risky edit without touching the parent session -- if the branch "
            "doesn't pan out, close_session it; if it does, merge_branch it "
            "back into the parent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The parent session to branch from.",
                },
                "version_id": {
                    "type": "string",
                    "description": (
                        "Optional. Fork from this specific historical version "
                        "of the parent instead of its current state. Recommended "
                        "when you intend to merge_branch the result back later: "
                        "it records the exact fork point merge_branch needs as "
                        "its merge base. Without it, merge_branch has no "
                        "automatic fork point and requires an explicit "
                        "'base_version_id' itself."
                    ),
                },
            },
            "required": ["session_id"],
        },
        "handler": log_tool_call("create_branch")(create_branch),
    },
    "merge_branch": {
        "name": "merge_branch",
        "description": (
            "Session-aware three-way merge: merge a branch session's changes "
            "into a target session. The merge base is resolved automatically "
            "from the branch's recorded fork point (set by create_branch), so "
            "-- unlike merge_knowledge -- you never supply the base yourself. "
            "On success, commits the merged result as a new version of the "
            "target session. On conflict, returns a 'conflicts' list "
            "(object_id, target_diff, source_diff) instead of merging. Do not "
            "call merge_branch again unchanged after a conflict -- retry it "
            "with a 'resolutions' argument covering each conflicting "
            "object_id (see the 'resolutions' parameter), which merges "
            "everything -- non-conflicting changes and now-resolved conflicts "
            "alike -- in this one call; identities you don't supply a "
            "resolution for are reported again. Only if you'd rather change "
            "the target session's content directly, apply your resolution "
            "there with evolve_knowledge and retry merge_branch with no "
            "resolutions. Either way, close_session the source branch once "
            "it has been fully integrated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_session_id": {
                    "type": "string",
                    "description": "The session to merge into.",
                },
                "source_session_id": {
                    "type": "string",
                    "description": "The branch session being merged in.",
                },
                "base_version_id": {
                    "type": "string",
                    "description": (
                        "Optional. Overrides the merge base with a specific "
                        "version id from the target session's history. Only "
                        "needed if source_session_id wasn't created with "
                        "create_branch's 'version_id' parameter."
                    ),
                },
                "resolutions": {
                    "type": "object",
                    "description": "Optional. Per-object conflict resolution strategies. Keys are object IDs. Values: 'branch_a' (take target's version), 'branch_b' (take source branch's version), null (drop the object), or a complete object definition to use as the merged result."
                }
            },
            "required": ["target_session_id", "source_session_id"],
        },
        "handler": log_tool_call("merge_branch")(merge_branch),
    },
    "close_session": {
        "name": "close_session",
        "description": (
            "Close a session, releasing it from the runtime. Typical use: "
            "after merge_branch reports success, close_session the source "
            "branch that was just merged in -- it has been integrated and no "
            "longer needs to stay open."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to close.",
                },
            },
            "required": ["session_id"],
        },
        "handler": log_tool_call("close_session")(close_session),
    },
    "query_subgraph": {
        "name": "query_subgraph",
        "description": (
            "Extract the local k‑hop neighbourhood around one or more seed ids "
            "from a session's current Knowledge Structure. Returns a self‑contained "
            "subgraph (serialized) and metadata: total_found_nodes, returned_nodes, "
            "is_truncated, truncation_reason, suggested_next_seed. "
            "Use filters (include_relation_types, include_object_types) to narrow "
            "the traversal, and max_tokens/max_objects to cap the result. "
            "type_weights can prioritise certain object types when the budget "
            "forces truncation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session whose Knowledge Structure to query."
                },
                "seed_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of object ids to start traversal from."
                },
                "depth": {
                    "type": "integer",
                    "description": "Maximum hops from any seed. Default 1."
                },
                "include_relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Only traverse/include these relation types."
                },
                "include_object_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Only include discovered objects of these types (seeds always kept)."
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional token budget (approx)."
                },
                "max_objects": {
                    "type": "integer",
                    "description": "Optional hard cap on total objects returned."
                },
                "type_weights": {
                    "type": "object",
                    "description": "Optional mapping of object type to weight (float), used in budget ranking."
                },
                "compact_mode": {
                    "type": "boolean",
                    "description": "If true, return a compact representation (nodes + edges) instead of full canonical JSON."
                },
            },
            "required": ["session_id"],
        },
        "handler": log_tool_call("query_subgraph")(query_subgraph_tool),
    },
    "search_semantic": {
        "name": "search_semantic",
        "description": (
            "Semantically search the Knowledge Structure of a session. "
            "Provide a natural language query; if the storage backend has "
            "a vector index (embeddings generated via the background "
            "outbox worker), matching seed objects are found "
            "automatically. Pass explicit 'seed_ids' instead when you "
            "already know which objects to expand around, or as a "
            "fallback if no embeddings have been generated yet for this "
            "session. The tool expands the neighbourhood around the "
            "matched seeds using query_subgraph. "
            "Use this when you don't know exact object IDs but have a "
            "description of what you're looking for."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to search in."
                },
                "query": {
                    "type": "string",
                    "description": "Natural language description of what to find."
                },
                "seed_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. List of object IDs to start the subgraph expansion from. Omit to use vector search automatically; required as a fallback if the storage backend has no embeddings for this session yet."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max number of seed objects to use (default 3)."
                },
                "depth": {
                    "type": "integer",
                    "description": "How many hops to expand around each seed (default 1)."
                },
            },
            "required": ["session_id", "query"],
        },
        "handler": log_tool_call("search_semantic")(search_semantic),
    },
    "get_metrics": {
        "name": "get_metrics",
        "description": "Return runtime metrics: invocation counts and average execution times for each operation type.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": log_tool_call("get_metrics")(get_metrics),
    },
    "verify_source": {
        "name": "verify_source",
        "description": "Verify an external source by performing a real HTTP request. Creates a VerificationRecord that can be validated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the source to verify."
                },
                "subject_id": {
                    "type": "string",
                    "description": "The ID of the Knowledge Object that this verification is about."
                }
            },
            "required": ["url", "subject_id"]
        },
        "handler": log_tool_call("verify_source")(verify_source),
    },
    "list_versions": {
        "name": "list_versions",
        "description": "List all available versions of a session's history. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The ID of the session to list versions for."
                }
            },
            "required": ["session_id"]
        },
        "handler": log_tool_call("list_versions")(list_versions),
    },
    "revert_version": {
        "name": "revert_version",
        "description": "Revert a session's Knowledge Structure to a specific previous version. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The ID of the session to revert."
                },
                "target_version_id": {
                    "type": "string",
                    "description": "The ID of the version to revert to."
                }
            },
            "required": ["session_id", "target_version_id"]
        },
        "handler": log_tool_call("revert_version")(revert_version),
    },
    "compare_versions": {
        "name": "compare_versions",
        "description": (
            "Compare the current state of a session against a target version. "
            "The returned diff is directional. "
            "'direction' explicitly describes how to interpret the changes. "
            "'base_version_id' is the historical version being compared against. "
            "'target_version_id' is the current session state. "
            "The response also contains a semantic summary (added/removed objects "
            "and relations) to make interpretation easier for LLMs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session whose current state will be compared."
                },
                "target_version_id": {
                    "type": "string",
                    "description": (
                        "Historical version to compare against. "
                        "The comparison is performed between this version "
                        "and the current state of the session."
                    )
                }
            },
            "required": [
                "session_id",
                "target_version_id"
            ]
        },
        "handler": log_tool_call("compare_versions")(compare_versions),
    },
    "visualize_graph": {
        "name": "visualize_graph",
        "description": (
            "Export a subgraph as a Mermaid diagram. Claude Desktop renders Mermaid "
            "natively, so the user sees the graph visually. Use this after "
            "query_subgraph to show the structure."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to visualize."
                },
                "seed_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional. Object IDs to start from. Defaults to all objects."
                },
                "depth": {
                    "type": "integer",
                    "description": "How many hops to expand. Default 1."
                },
                "max_objects": {
                    "type": "integer",
                    "description": "Max objects to include. Default 20."
                },
            },
            "required": ["session_id"],
        },
        "handler": log_tool_call("visualize_graph")(visualize_graph),
    },
    "explain_diff": {
        "name": "explain_diff",
        "description": (
            "Explain the differences between the current state of a session and a "
            "target version in plain English. Useful for understanding what changed "
            "without parsing raw diff output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to analyze."
                },
                "target_version_id": {
                    "type": "string",
                    "description": "The version to compare against."
                },
            },
            "required": ["session_id", "target_version_id"],
        },
        "handler": log_tool_call("explain_diff")(explain_diff),
    },
    "suggest_evolution": {
        "name": "suggest_evolution",
        "description": (
            "Given a session and a description of what to change, return the current "
            "objects/relations and guidance for constructing valid evolution operations. "
            "Use this to inspect the current state before calling evolve_knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to inspect."
                },
                "description": {
                    "type": "string",
                    "description": "What you want to change (e.g. 'add a new Concept about photosynthesis')."
                },
            },
            "required": ["session_id", "description"],
        },
        "handler": log_tool_call("suggest_evolution")(suggest_evolution),
    },
}