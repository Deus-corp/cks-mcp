"""
CKS MCP Tool Registry — assembles the TOOLS dict from each tool's
schema.py (JSON Schema) and handler.py (implementation), and applies
the middleware stack.

This module exists solely to keep the tool definitions out of server.py,
which remains responsible only for JSON-RPC transport. Adding a new tool
now touches exactly two places: its own package (in tools/<name>/) and
the TOOLS dict below.
"""

from __future__ import annotations

from cks_mcp.middleware import (
    catch_unhandled_errors,
    refresh_session_from_storage,
    require_fields,
    require_open_session,
    require_session,
    with_middleware,
)
from cks_mcp.observability import log_tool_call
from cks_mcp.tools.agent_status import agent_status
from cks_mcp.tools.agent_status.schema import AGENT_STATUS_SCHEMA
from cks_mcp.tools.ai_chat import ai_chat
from cks_mcp.tools.ai_chat.schema import AI_CHAT_SCHEMA
from cks_mcp.tools.approve_resolution import approve_resolution
from cks_mcp.tools.approve_resolution.schema import APPROVE_RESOLUTION_SCHEMA
from cks_mcp.tools.arbitrate_inference_conflict import arbitrate_inference_conflict
from cks_mcp.tools.arbitrate_inference_conflict.schema import (
    ARBITRATE_INFERENCE_CONFLICT_SCHEMA,
)
from cks_mcp.tools.branch import close_session, create_branch
from cks_mcp.tools.branch.schema import CLOSE_SESSION_SCHEMA, CREATE_BRANCH_SCHEMA
from cks_mcp.tools.check_component_versions import check_component_versions
from cks_mcp.tools.check_component_versions.schema import (
    CHECK_COMPONENT_VERSIONS_SCHEMA,
)
from cks_mcp.tools.check_graph_freshness import check_graph_freshness
from cks_mcp.tools.check_graph_freshness.schema import CHECK_GRAPH_FRESHNESS_SCHEMA
from cks_mcp.tools.check_graph_health import check_graph_health
from cks_mcp.tools.check_graph_health.schema import CHECK_GRAPH_HEALTH_SCHEMA
from cks_mcp.tools.claim_conflict_task import claim_conflict_task
from cks_mcp.tools.claim_conflict_task.schema import CLAIM_CONFLICT_TASK_SCHEMA
from cks_mcp.tools.clone_graph import clone_graph
from cks_mcp.tools.clone_graph.schema import CLONE_GRAPH_SCHEMA
from cks_mcp.tools.compare import compare_versions
from cks_mcp.tools.compare.schema import COMPARE_VERSIONS_SCHEMA
from cks_mcp.tools.compare_graphs import compare_graphs
from cks_mcp.tools.compare_graphs.schema import COMPARE_GRAPHS_SCHEMA
from cks_mcp.tools.complete_conflict_task import complete_conflict_task
from cks_mcp.tools.complete_conflict_task.schema import COMPLETE_CONFLICT_TASK_SCHEMA
from cks_mcp.tools.construct_knowledge import construct_knowledge
from cks_mcp.tools.construct_knowledge.schema import CONSTRUCT_KNOWLEDGE_SCHEMA
from cks_mcp.tools.dead_letter_conflict_task import dead_letter_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.schema import (
    DEAD_LETTER_CONFLICT_TASK_SCHEMA,
)
from cks_mcp.tools.detect_contradictions import detect_contradictions
from cks_mcp.tools.detect_contradictions.schema import DETECT_CONTRADICTIONS_SCHEMA
from cks_mcp.tools.evolve import evolve_knowledge
from cks_mcp.tools.evolve.schema import EVOLVE_KNOWLEDGE_SCHEMA
from cks_mcp.tools.explain import explain_knowledge
from cks_mcp.tools.explain.schema import EXPLAIN_KNOWLEDGE_SCHEMA
from cks_mcp.tools.explain_diff import explain_diff
from cks_mcp.tools.explain_diff.schema import EXPLAIN_DIFF_SCHEMA
from cks_mcp.tools.explain_graph import explain_graph
from cks_mcp.tools.explain_graph.schema import EXPLAIN_GRAPH_SCHEMA
from cks_mcp.tools.export_knowledge import export_knowledge
from cks_mcp.tools.export_knowledge.schema import EXPORT_KNOWLEDGE_SCHEMA
from cks_mcp.tools.export_session import export_session
from cks_mcp.tools.export_session.schema import EXPORT_SESSION_SCHEMA
from cks_mcp.tools.export_storage import export_storage
from cks_mcp.tools.export_storage.schema import EXPORT_STORAGE_SCHEMA
from cks_mcp.tools.fail_conflict_task import fail_conflict_task
from cks_mcp.tools.fail_conflict_task.schema import FAIL_CONFLICT_TASK_SCHEMA
from cks_mcp.tools.fork_sandbox import fork_sandbox
from cks_mcp.tools.fork_sandbox.schema import FORK_SANDBOX_SCHEMA
from cks_mcp.tools.get_graph import get_graph
from cks_mcp.tools.get_graph.schema import GET_GRAPH_SCHEMA
from cks_mcp.tools.get_llm_status import get_llm_status
from cks_mcp.tools.get_llm_status.schema import GET_LLM_STATUS_SCHEMA
from cks_mcp.tools.get_metrics import get_metrics
from cks_mcp.tools.get_metrics.schema import GET_METRICS_SCHEMA
from cks_mcp.tools.import_storage import import_storage
from cks_mcp.tools.import_storage.schema import IMPORT_STORAGE_SCHEMA
from cks_mcp.tools.ingest_document import ingest_document
from cks_mcp.tools.ingest_document.schema import INGEST_DOCUMENT_SCHEMA
from cks_mcp.tools.link_graphs import link_graphs
from cks_mcp.tools.link_graphs.schema import LINK_GRAPHS_SCHEMA
from cks_mcp.tools.list_agents import list_agents
from cks_mcp.tools.list_agents.schema import LIST_AGENTS_SCHEMA
from cks_mcp.tools.list_dead_lettered_conflicts import list_dead_lettered_conflicts
from cks_mcp.tools.list_dead_lettered_conflicts.schema import (
    LIST_DEAD_LETTERED_CONFLICTS_SCHEMA,
)
from cks_mcp.tools.list_gossip_conflicts import list_gossip_conflicts
from cks_mcp.tools.list_gossip_conflicts.schema import LIST_GOSSIP_CONFLICTS_SCHEMA
from cks_mcp.tools.list_graphs import list_graphs
from cks_mcp.tools.list_graphs.schema import LIST_GRAPHS_SCHEMA
from cks_mcp.tools.list_inference_conflicts import list_inference_conflicts
from cks_mcp.tools.list_inference_conflicts.schema import (
    LIST_INFERENCE_CONFLICTS_SCHEMA,
)
from cks_mcp.tools.list_llm_models import list_llm_models
from cks_mcp.tools.list_llm_models.schema import LIST_LLM_MODELS_SCHEMA
from cks_mcp.tools.list_pipeline_runs import list_pipeline_runs
from cks_mcp.tools.list_pipeline_runs.schema import LIST_PIPELINE_RUNS_SCHEMA
from cks_mcp.tools.list_plugins import list_plugins
from cks_mcp.tools.list_plugins.schema import LIST_PLUGINS_SCHEMA
from cks_mcp.tools.list_processes import list_processes
from cks_mcp.tools.list_processes.schema import LIST_PROCESSES_SCHEMA
from cks_mcp.tools.merge import merge_branch, merge_knowledge
from cks_mcp.tools.merge.schema import MERGE_BRANCH_SCHEMA, MERGE_KNOWLEDGE_SCHEMA
from cks_mcp.tools.merge_graphs import merge_graphs
from cks_mcp.tools.merge_graphs.schema import MERGE_GRAPHS_SCHEMA
from cks_mcp.tools.migrate_storage import migrate_storage
from cks_mcp.tools.migrate_storage.schema import MIGRATE_STORAGE_SCHEMA
from cks_mcp.tools.process_status import process_status
from cks_mcp.tools.process_status.schema import PROCESS_STATUS_SCHEMA
from cks_mcp.tools.query_subgraph import query_subgraph_tool
from cks_mcp.tools.query_subgraph.schema import QUERY_SUBGRAPH_SCHEMA
from cks_mcp.tools.refresh_verification import refresh_verification
from cks_mcp.tools.refresh_verification.schema import REFRESH_VERIFICATION_SCHEMA
from cks_mcp.tools.register_graph import register_graph
from cks_mcp.tools.register_graph.schema import REGISTER_GRAPH_SCHEMA
from cks_mcp.tools.reject_resolution import reject_resolution
from cks_mcp.tools.reject_resolution.schema import REJECT_RESOLUTION_SCHEMA
from cks_mcp.tools.request_enrichment import request_enrichment
from cks_mcp.tools.request_enrichment.schema import REQUEST_ENRICHMENT_SCHEMA
from cks_mcp.tools.request_process_stop import request_process_stop
from cks_mcp.tools.request_process_stop.schema import REQUEST_PROCESS_STOP_SCHEMA
from cks_mcp.tools.resolve_contradiction import resolve_contradiction
from cks_mcp.tools.resolve_contradiction.schema import RESOLVE_CONTRADICTION_SCHEMA
from cks_mcp.tools.resolve_gossip_conflict import resolve_gossip_conflict
from cks_mcp.tools.resolve_gossip_conflict.schema import (
    RESOLVE_GOSSIP_CONFLICT_SCHEMA,
)
from cks_mcp.tools.resolve_temporal_conflict import resolve_temporal_conflict
from cks_mcp.tools.resolve_temporal_conflict.schema import (
    RESOLVE_TEMPORAL_CONFLICT_SCHEMA,
)
from cks_mcp.tools.retry_dead_letter import retry_dead_letter
from cks_mcp.tools.retry_dead_letter.schema import RETRY_DEAD_LETTER_SCHEMA
from cks_mcp.tools.revert import list_versions, revert_version
from cks_mcp.tools.revert.schema import LIST_VERSIONS_SCHEMA, REVERT_VERSION_SCHEMA
from cks_mcp.tools.review_dead_letter import review_dead_letter
from cks_mcp.tools.review_dead_letter.schema import REVIEW_DEAD_LETTER_SCHEMA
from cks_mcp.tools.search_graphs import search_graphs
from cks_mcp.tools.search_graphs.schema import SEARCH_GRAPHS_SCHEMA
from cks_mcp.tools.search_semantic import search_semantic
from cks_mcp.tools.search_semantic.schema import SEARCH_SEMANTIC_SCHEMA
from cks_mcp.tools.serialize import serialize_knowledge
from cks_mcp.tools.serialize.schema import SERIALIZE_KNOWLEDGE_SCHEMA
from cks_mcp.tools.start_agent import start_agent
from cks_mcp.tools.start_agent.schema import START_AGENT_SCHEMA
from cks_mcp.tools.start_pipeline import start_pipeline
from cks_mcp.tools.start_pipeline.schema import START_PIPELINE_SCHEMA
from cks_mcp.tools.stop_agent import stop_agent
from cks_mcp.tools.stop_agent.schema import STOP_AGENT_SCHEMA
from cks_mcp.tools.suggest_evolution import suggest_evolution
from cks_mcp.tools.suggest_evolution.schema import SUGGEST_EVOLUTION_SCHEMA
from cks_mcp.tools.unregister_graph import unregister_graph
from cks_mcp.tools.unregister_graph.schema import UNREGISTER_GRAPH_SCHEMA
from cks_mcp.tools.update_graph_lifecycle import update_graph_lifecycle
from cks_mcp.tools.update_graph_lifecycle.schema import UPDATE_GRAPH_LIFECYCLE_SCHEMA
from cks_mcp.tools.update_registered_graph import update_registered_graph
from cks_mcp.tools.update_registered_graph.schema import (
    UPDATE_REGISTERED_GRAPH_SCHEMA,
)
from cks_mcp.tools.validate import validate_knowledge
from cks_mcp.tools.validate.schema import VALIDATE_KNOWLEDGE_SCHEMA
from cks_mcp.tools.verify_source import verify_source
from cks_mcp.tools.verify_source.schema import VERIFY_SOURCE_SCHEMA
from cks_mcp.tools.visualize_graph import visualize_graph
from cks_mcp.tools.visualize_graph.schema import VISUALIZE_GRAPH_SCHEMA

# ---------------------------------------------------------------------------
# Middleware stack builders
# ---------------------------------------------------------------------------


def _wrap(name: str, *required_fields: str):
    """Telemetry + unhandled-error catch + optional field validation."""
    if required_fields:
        return with_middleware(
            catch_unhandled_errors,
            require_fields(*required_fields),
            log_tool_call(name),
        )
    return with_middleware(
        catch_unhandled_errors,
        log_tool_call(name),
    )


def _wrap_session(name: str, *session_args: str):
    """Telemetry + unhandled-error catch + fresh-from-storage reload +
    session existence check.

    ``refresh_session_from_storage`` runs first (outermost of the
    session-related layers) so ``require_session``'s existence/open
    checks -- and the handler itself -- always see this session as it
    was most recently committed by *any* process sharing this
    backend, not just this one (see ``cks_mcp.session_refresh`` for
    why that matters: standalone agent processes like
    ``cks-pipeline-agent`` commit through their own ``Runtime``).
    """
    return with_middleware(
        catch_unhandled_errors,
        log_tool_call(name),
        refresh_session_from_storage(*session_args),
        require_session(*session_args),
    )


def _wrap_open_session(name: str, *session_args: str):
    """Telemetry + unhandled-error catch + fresh-from-storage reload +
    session must exist and be open."""
    return with_middleware(
        catch_unhandled_errors,
        log_tool_call(name),
        refresh_session_from_storage(*session_args),
        require_open_session(*session_args),
    )


def _wrap_open_session_fields(name: str, session_arg: str, *required_fields: str):
    """
    Telemetry + unhandled-error catch + required-field validation (for
    fields beyond the session id itself, e.g. arbitrate_inference_conflict's
    'conclusion_id') + fresh-from-storage reload + session must exist
    and be open. require_fields runs before require_open_session so a
    missing conclusion_id is reported on its own rather than as a
    session lookup failing on an unrelated arg.
    """
    return with_middleware(
        catch_unhandled_errors,
        log_tool_call(name),
        require_fields(*required_fields),
        refresh_session_from_storage(session_arg),
        require_open_session(session_arg),
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = {
    "ai_chat": {
        **AI_CHAT_SCHEMA,
        "handler": _wrap_open_session("ai_chat", "session_id")(ai_chat),
    },
    "validate_knowledge": {
        **VALIDATE_KNOWLEDGE_SCHEMA,
        "handler": _wrap_session("validate_knowledge", "session_id")(validate_knowledge),
    },
    "serialize_knowledge": {
        **SERIALIZE_KNOWLEDGE_SCHEMA,
        "handler": _wrap_session("serialize_knowledge", "session_id")(serialize_knowledge),
    },
    "explain_knowledge": {
        **EXPLAIN_KNOWLEDGE_SCHEMA,
        "handler": _wrap_session("explain_knowledge", "session_id")(explain_knowledge),
    },
    "evolve_knowledge": {
        **EVOLVE_KNOWLEDGE_SCHEMA,
        "handler": _wrap_open_session("evolve_knowledge", "session_id")(evolve_knowledge),
    },
    "merge_knowledge": {
        **MERGE_KNOWLEDGE_SCHEMA,
        "handler": _wrap(
            "merge_knowledge", "json_data_base", "json_data_branch_a", "json_data_branch_b"
        )(merge_knowledge),
    },
    "create_branch": {
        **CREATE_BRANCH_SCHEMA,
        "handler": _wrap_open_session("create_branch", "session_id")(create_branch),
    },
    "merge_branch": {
        **MERGE_BRANCH_SCHEMA,
        "handler": _wrap_open_session("merge_branch", "target_session_id")(merge_branch),
    },
    "close_session": {
        **CLOSE_SESSION_SCHEMA,
        "handler": _wrap_session("close_session", "session_id")(close_session),
    },
    "query_subgraph": {
        **QUERY_SUBGRAPH_SCHEMA,
        "handler": _wrap_session("query_subgraph", "session_id")(query_subgraph_tool),
    },
    "search_semantic": {
        **SEARCH_SEMANTIC_SCHEMA,
        "handler": _wrap_session("search_semantic", "session_id")(search_semantic),
    },
    "get_metrics": {
        **GET_METRICS_SCHEMA,
        "handler": _wrap("get_metrics")(get_metrics),
    },
    "get_llm_status": {
        **GET_LLM_STATUS_SCHEMA,
        "handler": _wrap("get_llm_status")(get_llm_status),
    },
    "list_llm_models": {
        **LIST_LLM_MODELS_SCHEMA,
        "handler": _wrap("list_llm_models")(list_llm_models),
    },
    "list_agents": {
        **LIST_AGENTS_SCHEMA,
        "handler": _wrap("list_agents")(list_agents),
    },
    "agent_status": {
        **AGENT_STATUS_SCHEMA,
        "handler": _wrap("agent_status", "agent_id")(agent_status),
    },
    "list_processes": {
        **LIST_PROCESSES_SCHEMA,
        "handler": _wrap("list_processes")(list_processes),
    },
    "process_status": {
        **PROCESS_STATUS_SCHEMA,
        "handler": _wrap("process_status", "process_kind")(process_status),
    },
    "start_agent": {
        **START_AGENT_SCHEMA,
        "handler": _wrap("start_agent", "agent_id")(start_agent),
    },
    "stop_agent": {
        **STOP_AGENT_SCHEMA,
        "handler": _wrap("stop_agent", "agent_id")(stop_agent),
    },
    "start_pipeline": {
        **START_PIPELINE_SCHEMA,
        "handler": _wrap_open_session("start_pipeline", "session_id")(start_pipeline),
    },
    "list_pipeline_runs": {
        **LIST_PIPELINE_RUNS_SCHEMA,
        "handler": _wrap_session("list_pipeline_runs", "session_id")(list_pipeline_runs),
    },
    "request_process_stop": {
        **REQUEST_PROCESS_STOP_SCHEMA,
        "handler": _wrap("request_process_stop", "process_kind")(request_process_stop),
    },
    "verify_source": {
        **VERIFY_SOURCE_SCHEMA,
        "handler": _wrap("verify_source", "url", "subject_id")(verify_source),
    },
    "list_versions": {
        **LIST_VERSIONS_SCHEMA,
        "handler": _wrap_session("list_versions", "session_id")(list_versions),
    },
    "revert_version": {
        **REVERT_VERSION_SCHEMA,
        "handler": _wrap_open_session("revert_version", "session_id")(revert_version),
    },
    "compare_versions": {
        **COMPARE_VERSIONS_SCHEMA,
        "handler": _wrap_session("compare_versions", "session_id")(compare_versions),
    },
    "visualize_graph": {
        **VISUALIZE_GRAPH_SCHEMA,
        "handler": _wrap_session("visualize_graph", "session_id")(visualize_graph),
    },
    "explain_diff": {
        **EXPLAIN_DIFF_SCHEMA,
        "handler": _wrap_session("explain_diff", "session_id")(explain_diff),
    },
    "export_knowledge": {
        **EXPORT_KNOWLEDGE_SCHEMA,
        "handler": _wrap_session("export_knowledge", "session_id")(export_knowledge),
    },
    "suggest_evolution": {
        **SUGGEST_EVOLUTION_SCHEMA,
        "handler": _wrap_open_session("suggest_evolution", "session_id")(suggest_evolution),
    },
    "detect_contradictions": {
        **DETECT_CONTRADICTIONS_SCHEMA,
        "handler": _wrap_session("detect_contradictions", "session_id")(detect_contradictions),
    },
    "fork_sandbox": {
        **FORK_SANDBOX_SCHEMA,
        "handler": _wrap_open_session("fork_sandbox", "session_id")(fork_sandbox),
    },
    "construct_knowledge": {
        **CONSTRUCT_KNOWLEDGE_SCHEMA,
        "handler": _wrap("construct_knowledge", "text")(construct_knowledge),
    },
    "export_session": {
        **EXPORT_SESSION_SCHEMA,
        "handler": _wrap_session("export_session", "session_id")(export_session),
    },
    "ingest_document": {
        **INGEST_DOCUMENT_SCHEMA,
        "handler": _wrap("ingest_document", "url")(ingest_document),
    },
    "list_gossip_conflicts": {
        **LIST_GOSSIP_CONFLICTS_SCHEMA,
        "handler": _wrap("list_gossip_conflicts")(list_gossip_conflicts),
    },
    "list_inference_conflicts": {
        **LIST_INFERENCE_CONFLICTS_SCHEMA,
        "handler": _wrap("list_inference_conflicts")(list_inference_conflicts),
    },
    "arbitrate_inference_conflict": {
        **ARBITRATE_INFERENCE_CONFLICT_SCHEMA,
        "handler": _wrap_open_session_fields(
            "arbitrate_inference_conflict", "session_id", "session_id", "conclusion_id"
        )(arbitrate_inference_conflict),
    },
    "claim_conflict_task": {
        **CLAIM_CONFLICT_TASK_SCHEMA,
        "handler": _wrap("claim_conflict_task", "task_type")(claim_conflict_task),
    },
    "complete_conflict_task": {
        **COMPLETE_CONFLICT_TASK_SCHEMA,
        "handler": _wrap("complete_conflict_task", "task_id")(complete_conflict_task),
    },
    "fail_conflict_task": {
        **FAIL_CONFLICT_TASK_SCHEMA,
        "handler": _wrap(
            "fail_conflict_task", "task_id", "retry_count", "error"
        )(fail_conflict_task),
    },
    "dead_letter_conflict_task": {
        **DEAD_LETTER_CONFLICT_TASK_SCHEMA,
        "handler": _wrap(
            "dead_letter_conflict_task", "task_id", "error"
        )(dead_letter_conflict_task),
    },
    "list_dead_lettered_conflicts": {
        **LIST_DEAD_LETTERED_CONFLICTS_SCHEMA,
        "handler": _wrap("list_dead_lettered_conflicts")(list_dead_lettered_conflicts),
    },
    "retry_dead_letter": {
        **RETRY_DEAD_LETTER_SCHEMA,
        "handler": _wrap("retry_dead_letter", "task_id")(retry_dead_letter),
    },
    "review_dead_letter": {
        **REVIEW_DEAD_LETTER_SCHEMA,
        "handler": _wrap("review_dead_letter", "task_id")(review_dead_letter),
    },
    "approve_resolution": {
        **APPROVE_RESOLUTION_SCHEMA,
        "handler": _wrap(
            "approve_resolution", "task_id", "resolution"
        )(approve_resolution),
    },
    "reject_resolution": {
        **REJECT_RESOLUTION_SCHEMA,
        "handler": _wrap("reject_resolution", "task_id")(reject_resolution),
    },
    "request_enrichment": {
        **REQUEST_ENRICHMENT_SCHEMA,
        "handler": _wrap("request_enrichment", "session_id", "object_id")(request_enrichment),
    },
    "resolve_gossip_conflict": {
        **RESOLVE_GOSSIP_CONFLICT_SCHEMA,
        "handler": _wrap_open_session(
            "resolve_gossip_conflict", "target_session_id", "source_session_id"
        )(resolve_gossip_conflict),
    },
    "refresh_verification": {
        **REFRESH_VERIFICATION_SCHEMA,
        "handler": _wrap_open_session_fields(
            "refresh_verification",
            "session_id",
            "session_id",
            "record_id",
            "subject_id",
            "source_url",
        )(refresh_verification),
    },
    "resolve_temporal_conflict": {
        **RESOLVE_TEMPORAL_CONFLICT_SCHEMA,
        "handler": _wrap_open_session_fields(
            "resolve_temporal_conflict",
            "session_id",
            "session_id",
            "object_id",
        )(resolve_temporal_conflict),
    },
    "resolve_contradiction": {
        **RESOLVE_CONTRADICTION_SCHEMA,
        "handler": _wrap_open_session(
            "resolve_contradiction", "session_id"
        )(resolve_contradiction),
    },
    "register_graph": {
        **REGISTER_GRAPH_SCHEMA,
        "handler": _wrap("register_graph", "name", "session_id")(register_graph),
    },
    "unregister_graph": {
        **UNREGISTER_GRAPH_SCHEMA,
        "handler": _wrap("unregister_graph", "name")(unregister_graph),
    },
    "get_graph": {
        **GET_GRAPH_SCHEMA,
        "handler": _wrap("get_graph", "name")(get_graph),
    },
    "clone_graph": {
        **CLONE_GRAPH_SCHEMA,
        "handler": _wrap_open_session(
            "clone_graph", "source_session_id", "target_session_id"
        )(clone_graph),
    },
    "compare_graphs": {
        **COMPARE_GRAPHS_SCHEMA,
        "handler": _wrap_open_session(
            "compare_graphs", "graph_a_session_id", "graph_b_session_id"
        )(compare_graphs),
    },
    "merge_graphs": {
        **MERGE_GRAPHS_SCHEMA,
        "handler": _wrap_open_session(
            "merge_graphs", "graph_a_session_id", "graph_b_session_id"
        )(merge_graphs),
    },
    "link_graphs": {
        **LINK_GRAPHS_SCHEMA,
        "handler": _wrap_open_session(
            "link_graphs",
            "graph_a_session_id",
            "graph_b_session_id",
        )(link_graphs),
    },
    "list_graphs": {
        **LIST_GRAPHS_SCHEMA,
        "handler": _wrap("list_graphs")(list_graphs),
    },
    "check_graph_freshness": {
        **CHECK_GRAPH_FRESHNESS_SCHEMA,
        "handler": _wrap("check_graph_freshness", "name")(check_graph_freshness),
    },
    "check_component_versions": {
        **CHECK_COMPONENT_VERSIONS_SCHEMA,
        "handler": _wrap("check_component_versions", "name")(check_component_versions),
    },
    "check_graph_health": {
        **CHECK_GRAPH_HEALTH_SCHEMA,
        "handler": _wrap("check_graph_health", "name")(check_graph_health),
    },
    "explain_graph": {
        **EXPLAIN_GRAPH_SCHEMA,
        "handler": _wrap("explain_graph", "name")(explain_graph),
    },
    "update_registered_graph": {
        **UPDATE_REGISTERED_GRAPH_SCHEMA,
        "handler": _wrap("update_registered_graph", "name")(update_registered_graph),
    },
    "update_graph_lifecycle": {
        **UPDATE_GRAPH_LIFECYCLE_SCHEMA,
        "handler": _wrap("update_graph_lifecycle", "name", "state")(
            update_graph_lifecycle
        ),
    },
    "search_graphs": {
        **SEARCH_GRAPHS_SCHEMA,
        "handler": _wrap("search_graphs", "query")(search_graphs),
    },
    "export_storage": {
        **EXPORT_STORAGE_SCHEMA,
        "handler": _wrap("export_storage")(export_storage),
    },
    "import_storage": {
        **IMPORT_STORAGE_SCHEMA,
        "handler": _wrap("import_storage", "file_path")(import_storage),
    },
    "migrate_storage": {
        **MIGRATE_STORAGE_SCHEMA,
        "handler": _wrap("migrate_storage", "target_backend", "target_path")(migrate_storage),
    },
    "list_plugins": {
        **LIST_PLUGINS_SCHEMA,
        "handler": _wrap("list_plugins")(list_plugins),
    },
}