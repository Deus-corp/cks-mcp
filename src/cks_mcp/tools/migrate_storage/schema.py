"""Input schema for the migrate_storage tool."""

from __future__ import annotations

MIGRATE_STORAGE_SCHEMA = {
    "name": "migrate_storage",
    "description": (
        "Copy all data from the current runtime storage into a new backend "
        "(SQLite file or Postgres DSN) without touching the live store. "
        "Exports data from the current backend, creates a fresh target backend, "
        "and imports into it. "
        "IMPORTANT: this tool does NOT hot-swap the runtime's active storage. "
        "To switch to the new backend you must restart the server with the "
        "updated CKS_STORAGE_BACKEND / CKS_DB_PATH / CKS_POSTGRES_DSN "
        "environment variables pointing at the new file or DSN. "
        "Returns a summary and the path/DSN of the new store."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "target_backend": {
                "type": "string",
                "enum": ["sqlite"],
                "description": (
                    "The storage backend to migrate to. "
                    "Currently only 'sqlite' is supported by this tool "
                    "(Postgres migration requires direct asyncpg access; "
                    "use export_storage + a custom script for that path)."
                ),
            },
            "target_path": {
                "type": "string",
                "description": (
                    "For target_backend='sqlite': filesystem path for the new .db file. "
                    "The file must not already exist (the tool will not overwrite it)."
                ),
            },
        },
        "required": ["target_backend", "target_path"],
    },
}