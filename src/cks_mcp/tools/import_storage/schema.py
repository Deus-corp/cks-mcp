"""Input schema for the import_storage tool."""

from __future__ import annotations

IMPORT_STORAGE_SCHEMA = {
    "name": "import_storage",
    "description": (
        "Restore a backup produced by export_storage into the current runtime storage. "
        "Reads the JSON dump from the given file and calls import_storage() on the "
        "active backend. "
        "mode='merge' (default) skips sessions/versions/graphs whose primary key already "
        "exists -- safe to run against a live store. "
        "mode='clear' truncates every table first, then inserts the snapshot -- use for "
        "full disaster-recovery restores on an empty or corrupted store. "
        "Returns a summary of what was imported."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the JSON dump file produced by export_storage.",
            },
            "mode": {
                "type": "string",
                "enum": ["merge", "clear"],
                "description": (
                    "'merge' (default) adds only new rows. "
                    "'clear' wipes the store before importing."
                ),
                "default": "merge",
            },
        },
        "required": ["file_path"],
    },
}