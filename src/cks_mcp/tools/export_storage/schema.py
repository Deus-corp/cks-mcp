"""Input schema for the export_storage tool."""

from __future__ import annotations

EXPORT_STORAGE_SCHEMA = {
    "name": "export_storage",
    "description": (
        "Export a complete backup of all runtime storage to a JSON file "
        "(sessions, versions, graph registry, embeddings, outbox tasks). "
        "The dump is written to a timestamped file on disk; the tool response "
        "returns only a summary (session/version/graph counts) and the file path "
        "-- never the full dump inline, as it may be very large. "
        "Use import_storage to restore from the file, or migrate_storage to "
        "copy data to a different backend."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "include_embeddings": {
                "type": "boolean",
                "description": (
                    "Whether to include raw embedding vectors in the dump. "
                    "Defaults to true. Set to false to produce a smaller file "
                    "when embeddings are not needed for the restore target."
                ),
                "default": True,
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Optional explicit path for the dump file. When omitted the "
                    "file is written to the system temp directory with a "
                    "timestamped name (cks_backup_<ISO8601>.json)."
                ),
            },
        },
        "required": [],
    },
}