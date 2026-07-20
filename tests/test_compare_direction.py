from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter
from cks_runtime.operations.operation_types import EvolveOperation
from cks_mcp.tools.compare import compare_versions
import cks
from cks.evolution import AddObject
from cks.core import KnowledgeObject, ObjectIdentity

runtime = Runtime(core=CksCoreAdapter())

# Create initial version with a valid KnowledgeStructure
obj1 = KnowledgeObject(identity=ObjectIdentity(id="obj-1", type="Concept", name="Testing"))
structure = cks.parse('{"objects": [{"identity": {"id": "obj-1", "type": "Concept", "name": "Testing"}, "structure": {}}]}')
session = runtime.create_session(structure)
tx = runtime.begin_transaction(session)
# Пустая эволюция, чтобы создать первую версию
tx.add_operation(EvolveOperation("evolve", knowledge_structure=structure, evolution=[]))
v1 = runtime.commit_transaction(tx)

# Evolve to version 2: добавляем объект
obj2 = KnowledgeObject(identity=ObjectIdentity(id="obj-2", type="Concept", name="Production"))
tx2 = runtime.begin_transaction(session)
tx2.add_operation(EvolveOperation("evolve", knowledge_structure=session.knowledge_structure, evolution=[AddObject(obj2)]))
v2 = runtime.commit_transaction(tx2)

# Compare current (v2) to base (v1) using the REAL compare_versions tool
result = compare_versions(runtime, {"session_id": session.session_id, "target_version_id": v1.version_id})

# Print results
print("Direction:", result["direction"])
print("Summary:", result["summary"])
assert result["direction"] == "base_to_current"
assert result["summary"]["added_objects"] == 1
assert result["summary"]["removed_objects"] == 0
print("OK: compare_versions has explicit direction")