import cks
import pytest
from cks.core import KnowledgeObject, ObjectIdentity
from cks.evolution import AddObject
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.runtime import Runtime

from cks_mcp.tools.compare.handler import compare_versions

pytestmark = pytest.mark.asyncio


async def test_compare_direction():
    runtime = Runtime(core=CksCoreAdapter())

    structure = cks.parse('{"objects": [{"identity": {"id": "obj-1", "type": "Concept", "name": "Testing"}, "structure": {}}]}')
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(EvolveOperation("evolve", knowledge_structure=structure, evolution=[]))
    v1 = await runtime.commit_transaction(tx)

    obj2 = KnowledgeObject(identity=ObjectIdentity(id="obj-2", type="Concept", name="Production"))
    tx2 = runtime.begin_transaction(session)
    tx2.add_operation(EvolveOperation("evolve", knowledge_structure=session.knowledge_structure, evolution=[AddObject(obj2)]))
    await runtime.commit_transaction(tx2)

    result = await compare_versions(runtime, {"session_id": session.session_id, "target_version_id": v1.version_id})

    assert result["direction"] == "base_to_current"
    assert result["summary"]["added_objects"] == 1
    assert result["summary"]["removed_objects"] == 0