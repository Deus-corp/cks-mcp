"""
MCP Tools – a thin wrapper around cks‑runtime operations.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import (
    ValidateOperation,
    EvolveOperation,
    SerializeOperation,
    ExplainOperation,
)
from cks_runtime.dispatcher.dispatcher import DispatchRequest


def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = json.loads(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ValidateOperation("validate", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)
    # Последний результат можно извлечь из диагностики или payload
    return {
        "valid": True,
        "version_id": version.version_id,
        "session_id": session.session_id,
    }


def serialize_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> str:
    structure = json.loads(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(SerializeOperation("serialize", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)
    # Результат сериализации можно было бы сохранить в payload операции,
    # но сейчас просто возвращаем заглушку. При реальном использовании
    # нужно получить результат из ExecutionResult.
    return json.dumps({"serialized": True, "version_id": version.version_id})


def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = json.loads(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ExplainOperation("explain", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)
    return {"explanation": "Not implemented", "version_id": version.version_id}


def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = json.loads(arguments["json_data"])
    operations = arguments["operations"]
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(EvolveOperation("evolve", knowledge_structure=structure, evolution=operations))
    version = runtime.commit_transaction(tx)
    return {"evolved": True, "version_id": version.version_id}