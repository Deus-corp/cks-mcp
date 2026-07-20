from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter
import cks

runtime = Runtime(core=CksCoreAdapter())

# Создаём корректную Knowledge Structure
structure = cks.parse('{"objects": [{"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}}]}')
session = runtime.create_session(structure)
tx = runtime.begin_transaction(session)
print("Transactions before commit:", len(runtime.transactions.list_transactions()))
runtime.commit_transaction(tx)
print("Transactions after commit:", len(runtime.transactions.list_transactions()))
assert len(runtime.transactions.list_transactions()) == 0, "Transaction should be removed after commit!"
print("OK: completed transaction removed from registry")