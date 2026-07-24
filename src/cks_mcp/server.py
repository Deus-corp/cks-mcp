"""
CKS MCP Server – Model Context Protocol over stdio.

A lightweight MCP server that exposes canonical CKS operations
(validate, serialize, explain, evolve, verify_source) to LLMs
via the Model Context Protocol.
"""

from __future__ import annotations

import os
import json
import sys
from typing import Any
import tempfile

from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter
from cks_runtime.storage.memory_storage import InMemoryStorage

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
from cks_mcp.observability import log_tool_call, setup_event_subscriptions
from cks_runtime.config import RuntimeConfig
from cks_mcp.resources import list_resources, read_resource
from cks_mcp.prompts import list_prompts, get_prompt, PROMPTS
from cks_mcp.tools.search_semantic import search_semantic
from cks_mcp.tools.get_metrics import get_metrics
from cks_runtime.embedding.client import HuggingFaceEmbeddingClient

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

SERVER_NAME = "cks-mcp"
SERVER_VERSION = "1.6.11"
PROTOCOL_VERSION = "2024-11-05"  # latest MCP protocol version

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
                        "'embedding_projection' and 'verification_record'. "
                        "Example of a correct EmbeddingProjection with its 'represents' relation: "
                        '{"objects": ['
                        '{"identity": {"id": "src-1", "type": "Document", "name": "Real paper"}, "structure": {}}, '
                        '{"identity": {"id": "proj-1", "type": "EmbeddingProjection", "name": "projection"}, "structure": {"store_ref": "vecdb://xyz"}}, '
                        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["src-1", "proj-1"], "relation_type": "represents"}}'
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
                        "object with a 'type' of 'add_object' | 'add_relation' | 'remove_object' "
                        "| 'remove_relation'. Example: "
                        '\'[{"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", '
                        '"name": "New"}, "structure": {}}, {"type": "add_relation", "identity": '
                        '{"id": "rel-1", "type": "Relation", "name": "r"}, "participants": '
                        '["obj-1", "obj-2"], "relation_type": "derives"}]\'.'
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
            "(object_id, base_state, target_state, source_state) instead of "
            "merging. Do not call merge_branch again unchanged after a "
            "conflict -- resolve each conflict on the target session with "
            "evolve_knowledge, then close_session the source branch once it "
            "has been fully integrated."
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
            },
            "required": ["session_id", "seed_ids"],
        },
        "handler": log_tool_call("query_subgraph")(query_subgraph_tool),
    },
    "search_semantic": {
        "name": "search_semantic",
        "description": (
            "Semantically search the Knowledge Structure of a session. "
            "Provide a natural language query and explicit seed object IDs "
            "(vector index coming soon). The tool expands the neighbourhood "
            "around the matched seeds using query_subgraph. "
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
                    "description": "List of object IDs to start the subgraph expansion from (required until vector index is available)."
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
}

# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def _make_response(request_id: Any, result: Any = None, error: dict | None = None) -> dict[str, Any]:
    """Wrap result/error into a JSON-RPC 2.0 response."""
    resp: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if result is not None:
        resp["result"] = result
    if error is not None:
        resp["error"] = error
    return resp


def handle_request(
    runtime: Runtime,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Handle a single JSON-RPC request."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
        })

    if method == "notifications/initialized":
        return {}

    if method == "ping":
        return _make_response(req_id, {})

    if method == "tools/list":
        return _make_response(req_id, {
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                }
                for tool in TOOLS.values()
            ],
        })

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        tool = TOOLS.get(tool_name)

        if tool is None:
            return _make_response(req_id, error={
                "code": -32601,
                "message": f"Unknown tool: {tool_name}",
            })

        handler = tool["handler"]
        try:
            result = handler(runtime, arguments)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
            })
        except Exception as e:
            error_message = str(e) if str(e) else "An internal error occurred."
            return _make_response(req_id, {
                "content": [{"type": "text", "text": f"Error: {error_message}"}],
                "isError": True
            })

    if method == "resources/list":
        try:
            resources = list_resources(runtime)
            return _make_response(req_id, {"resources": resources})
        except Exception as e:
            return _make_response(req_id, error={
                "code": -32603,
                "message": f"Failed to list resources: {e}",
            })

    if method == "resources/read":
        uri = params.get("uri")
        if not uri:
            return _make_response(req_id, error={
                "code": -32602,
                "message": "Missing required parameter: uri",
            })
        content = read_resource(runtime, uri)
        if content is None:
            return _make_response(req_id, error={
                "code": -32602,
                "message": f"Resource not found: {uri}",
            })
        return _make_response(req_id, {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": content,
                }
            ]
        })

    if method == "prompts/list":
        try:
            prompts = list_prompts()
            return _make_response(req_id, {"prompts": prompts})
        except Exception as e:
            return _make_response(req_id, error={
                "code": -32603,
                "message": f"Failed to list prompts: {e}",
            })

    if method == "prompts/get":
        name = params.get("name")
        if not name:
            return _make_response(req_id, error={
                "code": -32602,
                "message": "Missing required parameter: name",
            })
        args = params.get("arguments", {})
        prompt_message = get_prompt(name, args)
        if prompt_message is None:
            return _make_response(req_id, error={
                "code": -32602,
                "message": f"Prompt not found: {name}",
            })
        return _make_response(req_id, {
            "description": PROMPTS.get(name, {}).get("description", ""),
            "messages": prompt_message["messages"],
        })

    return _make_response(req_id, error={
        "code": -32601,
        "message": f"Method not found: {method}",
    })


def main() -> None:
    """Entry point for the MCP server."""
    # Determine a writable location for the SQLite database
    db_dir = "data"
    db_path = os.path.join(db_dir, "cks_mcp.db")
    storage = None
    use_persistent = True

    # Try to create the default data directory and check writability
    try:
        os.makedirs(db_dir, exist_ok=True)
        # Test write access
        test_file = os.path.join(db_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
    except (OSError, PermissionError) as e:
        # Default directory not writable – fall back to system temp
        use_persistent = False
        try:
            db_path = os.path.join(tempfile.gettempdir(), "cks_mcp.db")
            # Temp directory should be writable, but double-check
            with open(db_path, "a"):
                pass
            use_persistent = True
        except Exception as e2:
            # Even temp directory failed; use in-memory storage
            storage = InMemoryStorage()
            print(
                f"[CKS-MCP] WARNING: Could not open writable database file: {e} / {e2}. "
                "Using in-memory storage.",
                file=sys.stderr,
            )

    # Initialize embedding client (fallback to None if OpenAI unavailable)
    try:
        embedding_client = HuggingFaceEmbeddingClient()
    except Exception:
        embedding_client = None

    if storage is None and use_persistent:
        try:
            config = RuntimeConfig(storage_path=db_path)
            runtime = Runtime(core=CksCoreAdapter(), config=config, embedding_client=embedding_client)
        except Exception as e:
            print(
                f"[CKS-MCP] ERROR: Failed to initialize persistent storage: {e}. "
                "Falling back to in-memory storage.",
                file=sys.stderr,
            )
            storage = InMemoryStorage()
            runtime = Runtime(core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client)
    elif storage is not None:
        runtime = Runtime(core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client)
    else:
        # use_persistent is False but storage is still None (shouldn't happen)
        storage = InMemoryStorage()
        runtime = Runtime(core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client)

    setup_event_subscriptions(runtime)

    while True:
        line = sys.stdin.readline()
        if not line:
            return  # EOF

        line_stripped = line.strip()
        if line_stripped.lower().startswith("content-length:"):
            try:
                content_length = int(line_stripped.split(":")[1].strip())
            except (ValueError, IndexError):
                error_response = json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                })
                sys.stdout.write(error_response + "\n")
                sys.stdout.flush()
                continue
            sys.stdin.readline()
            body = sys.stdin.read(content_length)
            if not body:
                return
            process_request(runtime, body, use_content_length=True)
        elif line_stripped:
            process_request(runtime, line_stripped, use_content_length=False)


def process_request(runtime: Runtime, body: str, *, use_content_length: bool) -> None:
    """Process a single JSON-RPC request body and write the response."""
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": None,
        })
        if use_content_length:
            sys.stdout.write(f"Content-Length: {len(error_response.encode('utf-8'))}\r\n\r\n{error_response}")
        else:
            sys.stdout.write(error_response + "\n")
        sys.stdout.flush()
        return

    if isinstance(raw, list):
        responses = []
        for req in raw:
            resp = handle_request(runtime, req)
            if resp:
                responses.append(resp)
        if responses:
            _send_response(responses, use_content_length=use_content_length)
    else:
        resp = handle_request(runtime, raw)
        if resp:
            _send_response(resp, use_content_length=use_content_length)


def _send_response(response_obj: dict | list, *, use_content_length: bool = False) -> None:
    """Helper to send a response, optionally with Content-Length header."""
    body = json.dumps(response_obj, ensure_ascii=False)
    if use_content_length:
        sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    else:
        sys.stdout.write(body + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()