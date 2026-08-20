"""
Ecosystem integration smoke test for the CKS project.

Installs of ``cks-core``, ``cks-runtime`` and ``cks-mcp`` are assumed to
already be on ``sys.path`` (editable installs from each repo's ``main``
branch -- see ``.github/workflows/ecosystem-integration.yml``). This script
does not care about declared version numbers anywhere: it only exercises
the real, currently-installed code across package boundaries.

It is intentionally self-contained: no environment variables, no network
access, no external services. Everything runs against in-memory state.

Exit code 0 == success. Any failure raises / calls ``sys.exit(1)`` with a
descriptive message, after printing which stage failed.
"""

from __future__ import annotations

import asyncio
import sys
import traceback


def _fail(stage: str, exc: BaseException) -> None:
    print(f"\n[FAIL] {stage}", file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__)
    sys.exit(1)


def check_imports() -> None:
    """Stage 1: every key public import across the three packages works."""
    stage = "import checks"
    try:
        import cks  # noqa: F401
        import cks_runtime  # noqa: F401
        from cks.evolution import AddObject, compose  # noqa: F401
        from cks_runtime.adapters.cks_core import CksCoreAdapter  # noqa: F401

        import cks_mcp  # noqa: F401

        # cks_mcp.agents/__init__.py deliberately re-exports nothing (see
        # its docstring-less, empty module) -- agent_loop is reached as a
        # submodule import, which is the actual public path.
        from cks_mcp.agents import agent_loop  # noqa: F401
        from cks_mcp.llm.providers import (  # noqa: F401
            call_anthropic,
            call_google,
            call_ollama,
        )
        from cks_mcp.registry import TOOLS  # noqa: F401
    except Exception as exc:  # pragma: no cover - re-raised for CI logs  # noqa: BLE001
        _fail(stage, exc)

    print("[OK] all key public imports succeeded")


def check_tool_registry() -> None:
    """Stage 2: registry.TOOLS exposes at least 71 tools."""
    stage = "tool registry size check"
    try:
        from cks_mcp.registry import TOOLS

        count = len(TOOLS)
        assert count >= 71, f"expected at least 71 tools in registry.TOOLS, found {count}"
    except Exception as exc:  # noqa: BLE001
        _fail(stage, exc)

    print(f"[OK] registry.TOOLS contains {count} tools (>= 71)")


async def _lifecycle_scenario() -> str:
    """
    Stage 3: a real end-to-end knowledge lifecycle scenario using
    cks-runtime backed by InMemoryStorage + CksCoreAdapter, exercising
    session creation, validation, evolution, subgraph query, and
    branch creation / version listing.

    Returns the session_id, so the caller (stage 4) can reuse the same
    live Runtime/session to exercise an actual cks-mcp tool handler.
    """
    import cks
    from cks_runtime.adapters.cks_core import CksCoreAdapter
    from cks_runtime.operations.operation_types import (
        EvolveOperation,
        QuerySubgraphOperation,
        ValidateOperation,
    )
    from cks_runtime.runtime import Runtime
    from cks_runtime.storage.memory_storage import InMemoryStorage

    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())

    # --- minimal valid knowledge structure -------------------------------
    initial_structure = cks.KnowledgeStructure(
        [
            cks.KnowledgeObject(
                cks.ObjectIdentity(id="obj-1", type="Definition", name="Knowledge Object")
            )
        ]
    )

    session = await runtime.create_session(initial_structure)
    assert session.session_id, "create_session did not return a usable session"

    # --- validate ----------------------------------------------------------
    tx = runtime.begin_transaction(session)
    tx.add_operation(
        ValidateOperation("smoke-validate", knowledge_structure=session.knowledge_structure)
    )
    version = await runtime.commit_transaction(tx)
    assert version is not None, "validate commit did not produce a version"

    # --- evolve: add a second object ---------------------------------------
    tx = runtime.begin_transaction(session)
    tx.add_operation(
        EvolveOperation(
            "smoke-evolve",
            knowledge_structure=session.knowledge_structure,
            evolution=[
                cks.evolution.AddObject(
                    cks.KnowledgeObject(
                        cks.ObjectIdentity(id="obj-2", type="Theorem", name="New Object")
                    )
                )
            ],
        )
    )
    version = await runtime.commit_transaction(tx)
    assert version is not None, "evolve commit did not produce a version"
    assert any(
        obj.identity.id == "obj-2" for obj in session.knowledge_structure.objects
    ), "evolved object not present in session structure after commit"

    # --- query a subgraph around the new object -----------------------------
    op = QuerySubgraphOperation(
        "smoke-query-subgraph",
        knowledge_structure=session.knowledge_structure,
        seed_ids=["obj-2"],
        depth=1,
    )
    result = await runtime.executor.execute(op, session)
    assert result.status.value != "failed", f"query_subgraph failed: {result.error}"
    subgraph_object_ids = {obj.identity.id for obj in result.payload.structure.objects}
    assert "obj-2" in subgraph_object_ids, "query_subgraph result did not include the seed object"

    # --- branch + version listing -------------------------------------------
    # Branching/merging a full 3-way merge is heavier than a smoke test
    # needs; per the smoke-test scope, verify create_branch and version
    # listing (session.version_history) instead of a full merge round trip.
    branch = await runtime.create_branch(session)
    assert branch.session_id != session.session_id, "create_branch did not return a new session"
    assert branch.knowledge_structure is not None

    assert len(session.version_history) >= 2, (
        f"expected at least 2 versions on the original session, "
        f"found {len(session.version_history)}"
    )

    return session.session_id, branch.session_id, runtime


async def check_lifecycle_and_tool_handler() -> None:
    """Run stage 3 (lifecycle) then stage 4 (real cks-mcp tool handler)."""
    stage = "runtime knowledge lifecycle scenario"
    try:
        session_id, branch_session_id, runtime = await _lifecycle_scenario()
    except Exception as exc:  # noqa: BLE001
        _fail(stage, exc)

    print(
        "[OK] lifecycle scenario succeeded: session created, validated, "
        "evolved, subgraph queried, branch created "
        f"(session={session_id}, branch={branch_session_id})"
    )

    stage = "cks-mcp tool handler exercise (compare_versions)"
    try:
        from cks_mcp.tools.compare import compare_versions

        session = runtime.get_session(session_id)
        base_version_id = session.version_history[0].version_id

        result = await compare_versions(
            runtime,
            {"session_id": session_id, "target_version_id": base_version_id},
        )

        assert isinstance(result, dict), (
            f"compare_versions did not return a dict, got {type(result)!r}"
        )
        assert "error" not in result, (
            f"compare_versions returned an unexpected error for a basic "
            f"two-version session: {result.get('error')!r}"
        )
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001
        _fail(stage, exc)

    print(f"[OK] compare_versions tool handler returned a well-formed result: {list(result.keys())}")


def main() -> None:
    check_imports()
    check_tool_registry()
    asyncio.run(check_lifecycle_and_tool_handler())

    print("\n=== Ecosystem integration smoke test PASSED ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
