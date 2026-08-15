"""Input schema definition for the list_pipeline_runs tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_PIPELINE_RUNS_SCHEMA = {
    "name": "list_pipeline_runs",
    "description": "List recent ADR-007 pipeline runs (Researcher -> Synthesizer -> "
    "Reviewer -> Arbiter, started via start_pipeline) for a session, most "
    "recently updated first, including a per-step status/timestamps/error "
    "breakdown. Read-only: derives runs from each object's own "
    "transition_log entries (grouped by the run_id start_pipeline "
    "returned) plus any still-pending or dead-lettered pipeline outbox "
    "tasks, rather than a separate run-log table -- a run started before "
    "this tool existed, or whose objects have since been deleted, simply "
    "will not appear. Each run has 'run_id', 'session_id', 'status' "
    "('queued'|'running'|'completed'|'failed'), 'started_at', "
    "'updated_at', 'object_ids' (the objects start_pipeline was given), "
    "and 'steps' -- one entry per pipeline step name ('Researcher', "
    "'Synthesizer', 'Reviewer', 'Arbiter') with 'status' "
    "('pending'|'active'|'completed'|'failed'), 'started_at', "
    "'completed_at', 'error', and 'dead_letter_task_id'. Only Researcher "
    "and Reviewer are currently driven by start_pipeline (Milestone 1); "
    "Synthesizer/Arbiter entries report 'pending' for every run.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session whose pipeline runs should be listed.",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "description": "Maximum number of runs to return, most recent first.",
            },
        },
        "required": ["session_id"],
    },
}
