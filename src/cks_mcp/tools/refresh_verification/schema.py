"""Input schema definition for the refresh_verification tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention as every other
tool's schema.py, e.g. verify_source's).
"""

from __future__ import annotations

REFRESH_VERIFICATION_SCHEMA = {
    "name": "refresh_verification",
    "description": (
        "Resolve a provenance_conflict task (ADR-010's "
        "ProvenanceStalenessSweeper: a VerificationRecord whose checked_at "
        "has exceeded its TTL) by re-checking the original source and "
        "producing a fresh VerificationRecord. Unlike "
        "arbitrate_inference_conflict/resolve_gossip_conflict, there is no "
        "interactive or auto_resolve (LLM) path here: re-verifying a "
        "source is a mechanical HTTP check plus a cryptographic signature "
        "(exactly what verify_source already does), not a semantic "
        "judgment call, so this tool always re-runs verify_source itself. "
        "'auto_resolve' is still accepted, purely for call-shape parity "
        "with the Critic Agent's other conflict-resolution tools (see "
        "ProvenanceStalenessSweeper's docstring, which calls this as "
        "'refresh_verification(auto_resolve=True, commit=True)') -- it "
        "never triggers an LLM call and never changes what this tool "
        "does. Pass 'commit': true to have the new VerificationRecord "
        "(and its verified_by relation) applied to the session immediately "
        "via evolve_knowledge, instead of only returning it for the "
        "caller to apply itself."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session containing the stale VerificationRecord.",
            },
            "record_id": {
                "type": "string",
                "description": (
                    "The id of the stale VerificationRecord being refreshed "
                    "(the provenance_conflict task's 'record_id'). The "
                    "refreshed record gets a new id -- VerificationRecords "
                    "are immutable once signed -- this is used only to "
                    "report which record the refresh is for and, when "
                    "'commit' is true, to keep it in the response for "
                    "the caller's own bookkeeping."
                ),
            },
            "subject_id": {
                "type": "string",
                "description": (
                    "The id of the Knowledge Object the refreshed "
                    "VerificationRecord will be linked to via a "
                    "verified_by relation (the provenance_conflict task's "
                    "'subject_id')."
                ),
            },
            "source_url": {
                "type": "string",
                "description": (
                    "The URL to re-check (the provenance_conflict task's "
                    "'source_url'). Passed straight through to verify_source."
                ),
            },
            "auto_resolve": {
                "type": "boolean",
                "description": (
                    "Accepted for parity with the other conflict-resolution "
                    "tools' three-path shape; has no effect. This tool is "
                    "always mechanical and never calls an LLM."
                ),
            },
            "commit": {
                "type": "boolean",
                "description": (
                    "If true, apply the refreshed VerificationRecord (and "
                    "its verified_by relation) to 'session_id' via "
                    "evolve_knowledge and return the result as "
                    "'commit_result'."
                ),
            },
        },
        "required": ["session_id", "record_id", "subject_id", "source_url"],
    },
}