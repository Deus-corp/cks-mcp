# check_embeddings.py
import os
print(f"HF_TOKEN set: {bool(os.environ.get('HF_TOKEN'))}")
from cks_runtime.runtime import Runtime
from cks_runtime.config import RuntimeConfig
from cks_runtime_plugins.cks_core import CksCoreAdapter
import time

config = RuntimeConfig(storage_path="data/check_embeddings.db")
runtime = Runtime(core=CksCoreAdapter(), config=config)
print(f"Embedding client: {runtime.embedding_client}")
print(f"Outbox worker running: {runtime._outbox_worker._running}")

import cks
ks = cks.parse('{"objects":[{"identity":{"id":"obj-1","type":"Test","name":"t"},"structure":{"desc":"test"}}]}')
session = runtime.create_session(ks)
from cks_runtime.operations.operation_types import ValidateOperation
tx = runtime.begin_transaction(session)
tx.add_operation(ValidateOperation("v1", knowledge_structure=ks))
runtime.commit_transaction(tx)

time.sleep(5)
rows = runtime.storage._conn.execute("SELECT object_id FROM cks_object_embeddings").fetchall()
print(f"Stored embeddings after 5s: {len(rows)}")
if rows:
    from cks_runtime.embedding.client import HuggingFaceEmbeddingClient
    client = HuggingFaceEmbeddingClient()
    query_emb = client.embed_batch(["test"], normalize=True)[0]
    results = runtime.storage.search_embeddings(query_emb, session.session_id, top_k=3)
    print(f"Search results for 'test': {results}")