import json
import sqlite3
import uuid
from datetime import UTC, datetime

DB = "/tmp/cks-a/cks.db"
now = datetime.now(UTC).isoformat()

conn = sqlite3.connect(DB)

object_a_id = "concept-1-a"
object_b_id = "concept-1-b"

# 1. Вставляем объекты в G-Set (cks_knowledge_objects)
for oid in (object_a_id, object_b_id):
    obj = {
        "identity": {"id": oid, "type": "Concept", "name": "Test Concept"},
        "structure": {"description": f"Version from {oid.split('-')[-1]}"}
    }
    conn.execute(
        "INSERT OR IGNORE INTO cks_knowledge_objects (id, type, data) VALUES (?, ?, ?)",
        (oid, "KnowledgeObject", json.dumps(obj))
    )

# 2. Две записи в MV-Register (форк)
vector_clock_a = json.dumps({"replica-a": 1})
vector_clock_b = json.dumps({"replica-b": 1})

conn.execute(
    "INSERT INTO cks_mv_register (pointer_key, object_id, vector_clock, origin_node, created_at) VALUES (?, ?, ?, ?, ?)",
    ("concept-1", object_a_id, vector_clock_a, "replica-a", now)
)
conn.execute(
    "INSERT INTO cks_mv_register (pointer_key, object_id, vector_clock, origin_node, created_at) VALUES (?, ?, ?, ?, ?)",
    ("concept-1", object_b_id, vector_clock_b, "replica-b", now)
)

# 3. Конфликтное событие (обязательно поле vector_clocks)
event_id = str(uuid.uuid4())
conn.execute(
    """INSERT INTO cks_conflict_events
       (event_id, pointer_key, conflicting_object_ids, vector_clocks, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?)""",
    (event_id, "concept-1", json.dumps([object_a_id, object_b_id]),
     json.dumps({"replica-a": 1, "replica-b": 1}), "pending", now)
)

# 4. Задача для fork-агента в outbox
conn.execute(
    "INSERT INTO cks_outbox_tasks (task_type, session_id, payload, status, created_at) VALUES (?, ?, ?, ?, ?)",
    ("crdt_fork", "concept-1", json.dumps({
        "pointer_key": "concept-1",
        "conflicting_object_ids": [object_a_id, object_b_id],
        "event_id": event_id
    }), "PENDING", now)
)

conn.commit()
conn.close()
print("Fork injected successfully.")