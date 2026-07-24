# diagnostics_rag.py
import time
import cks
from cks_runtime.runtime import Runtime
from cks_runtime.config import RuntimeConfig
from cks_runtime_plugins.cks_core import CksCoreAdapter

# 1. Создаём рантайм с персистентным SQLite
config = RuntimeConfig(storage_path="data/test_rag.db")
runtime = Runtime(core=CksCoreAdapter(), config=config)

# 2. Строим простой граф
ks = cks.parse(
    '{"objects":['
    '{"identity":{"id":"ec2","type":"Compute","name":"EC2"},"structure":{"desc":"virtual machine service"}},'
    '{"identity":{"id":"s3","type":"Storage","name":"S3"},"structure":{"desc":"object storage"}},'
    '{"identity":{"id":"rel-aws-ec2","type":"Relation","name":"r1"},"structure":{"participants":["ec2","s3"],"relation_type":"connects"}}'
    ']}'
)
session = runtime.create_session(ks)
from cks_runtime.operations.operation_types import ValidateOperation
tx = runtime.begin_transaction(session)
tx.add_operation(ValidateOperation("v1", knowledge_structure=ks))
version = runtime.commit_transaction(tx)
print(f"1. Session {session.session_id} created, version {version.version_id}")

# 3. Ждём 5 секунд, чтобы воркер обработал outbox
print("2. Waiting for embedding worker...")
time.sleep(5)

# 4. Проверяем таблицы напрямую
outbox_rows = runtime.storage._conn.execute("SELECT * FROM cks_outbox_tasks").fetchall()
print(f"3. Outbox tasks: {len(outbox_rows)} (0 means tasks were processed or never created)")

emb_rows = runtime.storage._conn.execute("SELECT object_id, length(embedding) FROM cks_object_embeddings").fetchall()
print(f"4. Stored embeddings: {len(emb_rows)} (should be 2 — ec2 and s3)")
for obj_id, emb_len in emb_rows:
    print(f"   {obj_id}: {emb_len} bytes")

# 5. Пробуем поиск (если эмбеддинги есть)
if emb_rows:
    print("5. Testing search...")
    from cks_runtime.embedding.client import HuggingFaceEmbeddingClient
    client = HuggingFaceEmbeddingClient()
    query_emb = client.embed_batch(["virtual machines"], normalize=True)[0]
    results = runtime.storage.search_embeddings(query_emb, session.session_id, top_k=3)
    print(f"   Search results for 'virtual machines': {results}")
    print("   Expected: ec2 should be first")
else:
    print("5. No embeddings to search — check worker logs above.")