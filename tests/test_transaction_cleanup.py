import cks
import pytest
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.runtime import Runtime

pytestmark = pytest.mark.asyncio


async def test_transaction_cleanup():
    runtime = Runtime(core=CksCoreAdapter())
    structure = cks.parse('{"objects": [{"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}}]}')
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    assert len(runtime.transactions.list_transactions()) == 1
    await runtime.commit_transaction(tx)
    assert len(runtime.transactions.list_transactions()) == 0
    await runtime.aclose()