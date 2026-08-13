from __future__ import annotations

START_PIPELINE_SCHEMA = {
    "name": "start_pipeline",
    "description": (
        "Kick off an ADR-007 agent pipeline run (Researcher -> Reviewer -> "
        "Synthesizer -> Arbiter) against a session's objects by enqueueing "
        "'pipeline_research_request' tasks into the persistent outbox -- the "
        "same task_type a running 'cks-pipeline-agent' process (CKSAgentOrchestrator) "
        "already drains. This tool only enqueues; it returns immediately without "
        "waiting for any step to actually run. A 'cks-pipeline-agent' process must "
        "be running against the same storage backend for the enqueued objects to "
        "make progress -- this tool does not start one. Requires a storage backend "
        "that supports the outbox (SQLite or Postgres); returns 'supported': false "
        "under the default in-memory backend."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session whose objects the pipeline should process.",
            },
            "object_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional. Specific object ids to run the pipeline against. "
                    "Omit to enqueue every object currently in the session."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["sequential", "concurrent"],
                "default": "sequential",
                "description": (
                    "Optional, default 'sequential'. Recorded on the returned run "
                    "identity (see pipeline_run_hash) and, for a caller that also "
                    "owns its own CKSAgentOrchestrator instance, is the natural "
                    "argument to pass through to run_sequential/run_concurrent. "
                    "The standalone 'cks-pipeline-agent' process only ever calls "
                    "run_sequential today, so 'concurrent' has no effect on tasks "
                    "picked up by that process -- it only matters for a caller "
                    "driving its own orchestrator."
                ),
            },
            "parent_session_id": {
                "type": "string",
                "description": (
                    "Optional. Phase 1 sandbox isolation: fork this session first "
                    "(see fork_sandbox) and enqueue the pipeline against the "
                    "resulting sandbox branch instead of session_id directly, so "
                    "the run's own evolve_knowledge writes never touch the parent "
                    "session until a separate merge_branch call. When set, "
                    "'session_id' should normally equal 'parent_session_id' (the "
                    "session to fork); the two are accepted separately so a caller "
                    "that already forked a sandbox out-of-band can pass its id as "
                    "'session_id' and skip forking again by omitting "
                    "'parent_session_id'."
                ),
            },
            "schema_version": {
                "type": "string",
                "default": "v1",
                "description": (
                    "Optional, default 'v1'. Pipeline schema version, folded into "
                    "the returned run_id (see cks_mcp.orchestrator.pipeline_run_hash) "
                    "so runs against different schema versions never collide."
                ),
            },
        },
        "required": ["session_id"],
    },
}
