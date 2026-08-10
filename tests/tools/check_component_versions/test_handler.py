"""Unit tests for the check_component_versions MCP tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cks_mcp.tools.check_component_versions.handler import (
    _compare_versions,
    _pkg_name,
    _repo_from_url,
    _resolve_component,
    _version_tuple,
    check_component_versions,
)
from cks_mcp.tools.verify_source.handler import UnsafeURLError

# pyproject.toml sets asyncio_mode = "auto", so async test functions are
# picked up automatically -- no pytestmark needed (and adding one would
# incorrectly tag this file's sync helper-function tests too).


def _obj(obj_id: str, obj_type: str, name: str, structure: dict) -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(id=obj_id, type=obj_type, name=name),
        structure=structure,
    )


@dataclass
class _FakeStructure:
    objects: list = field(default_factory=list)


def _mock_runtime(*, graph_record=None, session=None):
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=graph_record)
    runtime.get_session = MagicMock(return_value=session)
    return runtime


def _mock_response(status_code: int, text: str) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, text=text)


# ---------------------------------------------------------------------------
# Parameter / graph / session validation
# ---------------------------------------------------------------------------


async def test_missing_name():
    runtime = _mock_runtime()
    result = await check_component_versions(runtime, {})
    assert result.get("error") == "missing_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_graph_not_found():
    runtime = _mock_runtime(graph_record=None)
    result = await check_component_versions(runtime, {"name": "unknown"})
    assert result == {"found": False}


async def test_session_not_available():
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=None
    )
    result = await check_component_versions(runtime, {"name": "cks-ecosystem"})
    assert result["found"] is True
    assert result["error"] == "session_not_available"
    assert "s1" in result["message"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_repo_from_url_basic():
    assert _repo_from_url("https://github.com/Deus-corp/cks-core") == "Deus-corp/cks-core"


def test_repo_from_url_with_git_suffix_and_tree():
    assert (
        _repo_from_url("https://github.com/Deus-corp/cks-core.git/tree/main")
        == "Deus-corp/cks-core"
    )


def test_repo_from_url_non_github():
    assert _repo_from_url("https://gitlab.com/foo/bar") is None


def test_pkg_name():
    assert _pkg_name("cks-core") == "cks_core"


def test_version_tuple_numeric():
    assert _version_tuple("1.21.0") == (1, 21, 0)


def test_version_tuple_non_string():
    assert _version_tuple(None) is None


def test_compare_versions_equal():
    assert _compare_versions("1.21.0", "1.21.0") == "up_to_date"


def test_compare_versions_outdated():
    assert _compare_versions("1.21.0", "1.22.0") == "outdated"


def test_compare_versions_outdated_minor_vs_double_digit():
    # Lexical string comparison would get this backwards ("1.9.0" > "1.10.0").
    assert _compare_versions("1.9.0", "1.10.0") == "outdated"


def test_compare_versions_ahead():
    assert _compare_versions("1.22.0", "1.21.0") == "ahead"


def test_compare_versions_unparsable_falls_back_to_outdated():
    assert _compare_versions("not-a-version", "1.21.0") == "outdated"


def test_resolve_component_known():
    repo, paths, source = _resolve_component("cks-core", {})
    assert repo == "Deus-corp/cks-core"
    assert paths == ("src/cks/_version.py",)
    assert source == "python"


def test_resolve_component_via_repo_url():
    repo, paths, source = _resolve_component(
        "some-plugin", {"repo_url": "https://github.com/acme/some-plugin"}
    )
    assert repo == "acme/some-plugin"
    assert paths[0] == "_version.py"
    assert "some_plugin" in paths[1]
    assert source == "python"


def test_resolve_component_unknown():
    repo, paths, source = _resolve_component("mystery", {})
    assert repo is None
    assert paths == ()
    assert source == "python"


def test_resolve_component_npm_via_repo_url():
    repo, paths, source = _resolve_component(
        "cks-studio",
        {
            "repo_url": "https://github.com/Deus-corp/cks-studio",
            "version_source": "package.json",
        },
    )
    assert repo == "Deus-corp/cks-studio"
    assert paths[0] == "package.json"
    assert source == "package_json"


def test_resolve_component_npm_known_component_falls_back_to_repo():
    # A _KNOWN_COMPONENTS entry with version_source=package.json still
    # resolves against that repo, just via the npm strategy instead of
    # the Python one.
    repo, _paths, source = _resolve_component(
        "cks-core", {"version_source": "package.json"}
    )
    assert repo == "Deus-corp/cks-core"
    assert source == "package_json"


# ---------------------------------------------------------------------------
# End-to-end handler behavior (network calls mocked via _safe_request)
# ---------------------------------------------------------------------------


async def test_no_components_in_graph():
    structure = _FakeStructure(objects=[_obj("o1", "Fact", "not-a-component", {})])
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result == {"found": True, "components": []}


async def test_up_to_date_known_component():
    structure = _FakeStructure(
        objects=[
            _obj("c1", "Component", "cks-core", {"version": "1.21.0"}),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(200, '__version__ = "1.21.0"\n'),
    ) as mock_request:
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["found"] is True
    assert result["components"] == [
        {
            "component": "cks-core",
            "graph_version": "1.21.0",
            "actual_version": "1.21.0",
            "status": "up_to_date",
        }
    ]
    mock_request.assert_called_once_with(
        "https://raw.githubusercontent.com/Deus-corp/cks-core/main/src/cks/_version.py"
    )


async def test_outdated_component():
    structure = _FakeStructure(
        objects=[
            _obj("c1", "Component", "cks-core", {"version": "1.21.0"}),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(200, '__version__ = "1.22.0"\n'),
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0] == {
        "component": "cks-core",
        "graph_version": "1.21.0",
        "actual_version": "1.22.0",
        "status": "outdated",
    }


async def test_unknown_repo_component_without_repo_url():
    structure = _FakeStructure(
        objects=[_obj("c1", "Component", "mystery-plugin", {"version": "1.0.0"})]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "unknown_repo"
    assert result["components"][0]["actual_version"] is None


async def test_component_via_repo_url():
    structure = _FakeStructure(
        objects=[
            _obj(
                "c1",
                "Component",
                "some-plugin",
                {"version": "0.9.0", "repo_url": "https://github.com/acme/some-plugin"},
            ),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    # First candidate path ("_version.py") 404s, second
    # ("some_plugin/_version.py") succeeds.
    responses = [_mock_response(404, ""), _mock_response(200, '__version__ = "0.9.0"\n')]

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        side_effect=responses,
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "up_to_date"
    assert result["components"][0]["actual_version"] == "0.9.0"


async def test_fetch_failed_all_candidates_404():
    structure = _FakeStructure(
        objects=[_obj("c1", "Component", "cks-core", {"version": "1.21.0"})]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(404, ""),
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "fetch_failed"
    assert result["components"][0]["actual_version"] is None
    assert result["components"][0]["message"] is not None


async def test_unsafe_url_reported_not_raised():
    structure = _FakeStructure(
        objects=[
            _obj(
                "c1",
                "Component",
                "some-plugin",
                {"version": "1.0.0", "repo_url": "https://github.com/acme/some-plugin"},
            ),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        side_effect=UnsafeURLError("refusing non-public host"),
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "fetch_failed"
    assert "unsafe_url" in result["components"][0]["message"]


async def test_ignores_components_without_version_field():
    structure = _FakeStructure(
        objects=[
            _obj("c1", "Component", "no-version-here", {"repo_url": "https://github.com/a/b"}),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result == {"found": True, "components": []}


async def test_multiple_components_mixed_statuses():
    structure = _FakeStructure(
        objects=[
            _obj("c1", "Component", "cks-core", {"version": "1.21.0"}),
            _obj("c2", "Component", "cks-runtime", {"version": "1.41.0"}),
            _obj("c3", "Component", "unknown-thing", {"version": "1.0.0"}),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    def fake_safe_request(url, **kwargs):
        if "cks-core" in url:
            return _mock_response(200, '__version__ = "1.22.0"\n')  # outdated
        if "cks-runtime" in url:
            return _mock_response(200, '__version__ = "1.41.0"\n')  # up to date
        return _mock_response(404, "")

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        side_effect=fake_safe_request,
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    statuses = {c["component"]: c["status"] for c in result["components"]}
    assert statuses == {
        "cks-core": "outdated",
        "cks-runtime": "up_to_date",
        "unknown-thing": "unknown_repo",
    }

# ---------------------------------------------------------------------------
# package.json (npm) version source
# ---------------------------------------------------------------------------


async def test_npm_component_up_to_date():
    structure = _FakeStructure(
        objects=[
            _obj(
                "c1",
                "Component",
                "cks-studio",
                {
                    "version": "v0.5.9",
                    "repo_url": "https://github.com/Deus-corp/cks-studio",
                    "version_source": "package.json",
                },
            ),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(200, '{"name": "cks-studio", "version": "0.5.9"}'),
    ) as mock_request:
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"] == [
        {
            "component": "cks-studio",
            "graph_version": "v0.5.9",
            "actual_version": "0.5.9",
            "status": "up_to_date",
        }
    ]
    mock_request.assert_called_once_with(
        "https://raw.githubusercontent.com/Deus-corp/cks-studio/main/package.json"
    )


async def test_npm_component_outdated():
    structure = _FakeStructure(
        objects=[
            _obj(
                "c1",
                "Component",
                "cks-studio",
                {
                    "version": "v0.5.9",
                    "repo_url": "https://github.com/Deus-corp/cks-studio",
                    "version_source": "package.json",
                },
            ),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(200, '{"name": "cks-studio", "version": "0.6.0"}'),
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "outdated"
    assert result["components"][0]["actual_version"] == "0.6.0"


async def test_npm_component_no_version_field_falls_back_to_fetch_failed():
    structure = _FakeStructure(
        objects=[
            _obj(
                "c1",
                "Component",
                "cks-studio",
                {
                    "version": "v0.5.9",
                    "repo_url": "https://github.com/Deus-corp/cks-studio",
                    "version_source": "package.json",
                },
            ),
        ]
    )
    session = SimpleNamespace(knowledge_structure=structure)
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=session
    )

    with patch(
        "cks_mcp.tools.check_component_versions.handler._safe_request",
        return_value=_mock_response(200, '{"name": "cks-studio"}'),
    ):
        result = await check_component_versions(runtime, {"name": "cks-ecosystem"})

    assert result["components"][0]["status"] == "fetch_failed"
    assert result["components"][0]["actual_version"] is None
