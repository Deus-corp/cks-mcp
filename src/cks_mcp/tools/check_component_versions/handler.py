"""
check_component_versions: cross-check the version recorded on a
registered ecosystem graph's ``Component`` objects against the real
``__version__`` published in each component's GitHub repository, so a
graph that has drifted out of date with the code it describes gets
caught instead of silently trusted.

Read-only: this never writes back to the graph or session, and it
never mutates the source repositories -- it only fetches
``_version.py`` over the GitHub raw API. All outbound requests go
through ``verify_source``'s ``_safe_request``, so they get the same
SSRF/DNS-rebinding protection real HTTP checks elsewhere in cks-mcp
get, rather than a second, unaudited ``requests.get`` path.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter
from cks_mcp.tools.verify_source.handler import UnsafeURLError, _safe_request

_VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")

_DEFAULT_BRANCH = "main"

# Components whose repo layout we know outright, so we don't have to
# guess at _version.py's location for the core CKS ecosystem itself.
# Keyed by the Component object's identity.name (falling back to
# identity.id) as registered in the graph, e.g. "cks-core".
_KNOWN_COMPONENTS: dict[str, dict[str, str]] = {
    "cks-core": {"repo": "Deus-corp/cks-core", "path": "src/cks/_version.py"},
    "cks-runtime": {"repo": "Deus-corp/cks-runtime", "path": "cks_runtime/_version.py"},
    "cks-mcp": {"repo": "Deus-corp/cks-mcp", "path": "src/cks_mcp/_version.py"},
}

# Candidate _version.py locations tried, in order, for a component
# whose repository is known (via a 'repo_url' field on the Component
# object) but whose internal package layout isn't. `{pkg}` is the
# component name with '-' replaced by '_' (e.g. "cks-core" -> "cks_core").
_CANDIDATE_PATHS = (
    "_version.py",
    "{pkg}/_version.py",
    "src/{pkg}/_version.py",
)


def _repo_from_url(repo_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub repo URL, or None if not GitHub."""
    parsed = urlparse(repo_url)
    if not parsed.netloc or "github.com" not in parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    repo = repo.removesuffix(".git")
    return f"{owner}/{repo}"


def _pkg_name(component_name: str) -> str:
    return component_name.replace("-", "_")


def _raw_url(repo: str, path: str, branch: str = _DEFAULT_BRANCH) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _fetch_version_sync(repo: str, candidate_paths: tuple[str, ...]) -> tuple[str | None, str | None]:
    """
    Try each candidate path against `repo`'s default branch until one
    resolves (via the GitHub raw API) to a parsable ``__version__``.

    Returns ``(version, error)`` where exactly one of the two is
    ``None``. Performs blocking network I/O, so callers should run it
    via ``asyncio.to_thread`` rather than calling it directly from
    an async handler.
    """
    last_error: str | None = None
    for path in candidate_paths:
        url = _raw_url(repo, path)
        try:
            resp = _safe_request(url)
        except UnsafeURLError as exc:
            return None, f"unsafe_url: {exc}"
        if resp is None or resp.status_code != 200:
            last_error = f"could not fetch {url}"
            continue
        match = _VERSION_RE.search(resp.text)
        if not match:
            last_error = f"no __version__ found at {url}"
            continue
        return match.group(1), None
    return None, last_error or f"no candidate paths for {repo}"


def _version_tuple(version: Any) -> tuple[int, ...] | None:
    """
    Parse a plain dotted-numeric version string ("1.21.0") into a
    comparable tuple of ints. Returns None for anything that isn't
    strictly numeric-dotted (e.g. "1.2.0-rc1", "v1.2", or a non-string),
    since those need string-level fallback comparison instead -- a
    tuple that mixed ints and strings would compare unpredictably
    against a purely-numeric tuple.
    """
    if not isinstance(version, str):
        return None
    parts = []
    for chunk in version.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return None
    return tuple(parts)


def _compare_versions(graph_version: Any, actual_version: str) -> str:
    """
    Classify `graph_version` (from the graph) against `actual_version`
    (fetched from GitHub): 'up_to_date', 'outdated', or 'ahead'.

    Falls back to plain string equality/ordering when either version
    doesn't parse as a dotted version, since an exact string match is
    still meaningful even when we can't order two malformed values.
    """
    if graph_version == actual_version:
        return "up_to_date"

    graph_tuple = _version_tuple(graph_version)
    actual_tuple = _version_tuple(actual_version)
    if graph_tuple is not None and actual_tuple is not None:
        if graph_tuple < actual_tuple:
            return "outdated"
        if graph_tuple > actual_tuple:
            return "ahead"
        return "up_to_date"

    # Unparsable on one side or the other: we already know they're not
    # equal, so report the safer of the two guesses -- outdated -- since
    # that's the case this tool exists to catch, rather than silently
    # picking "ahead".
    return "outdated"


def _resolve_component(
    component_name: str, structure: dict[str, Any]
) -> tuple[str | None, tuple[str, ...]]:
    """
    Work out which GitHub repo (and which _version.py paths to try in
    it) a Component object corresponds to. Returns (repo, candidate_paths);
    repo is None if it couldn't be determined at all.
    """
    known = _KNOWN_COMPONENTS.get(component_name)
    if known is not None:
        return known["repo"], (known["path"],)

    repo_url = structure.get("repo_url")
    if repo_url:
        repo = _repo_from_url(repo_url)
        if repo is not None:
            pkg = _pkg_name(component_name)
            return repo, tuple(p.format(pkg=pkg) for p in _CANDIDATE_PATHS)

    return None, ()


async def check_component_versions(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    record = await runtime.storage.get_graph(name)
    if record is None:
        return {"found": False}

    session_id = record.get("session_id")
    session = runtime.get_session(session_id)
    if not session:
        # The graph is registered, but the session it points at isn't
        # currently loaded (closed/evicted) -- report this rather than
        # raising, matching check_graph_freshness's style of surfacing
        # missing state as a result field instead of an exception.
        return {
            "found": True,
            "session_id": session_id,
            "error": "session_not_available",
            "message": f"Session '{session_id}' for graph '{name}' is not currently loaded.",
        }

    components = [
        obj
        for obj in session.knowledge_structure.objects
        if getattr(getattr(obj, "identity", None), "type", None) == "Component"
        and "version" in getattr(obj, "structure", {})
    ]

    results: list[dict[str, Any]] = []

    for obj in components:
        component_name = obj.identity.name or obj.identity.id
        graph_version = obj.structure.get("version")

        repo, candidate_paths = _resolve_component(component_name, obj.structure)
        if repo is None:
            results.append(
                {
                    "component": component_name,
                    "graph_version": graph_version,
                    "actual_version": None,
                    "status": "unknown_repo",
                    "message": (
                        f"Could not determine a GitHub repository for "
                        f"'{component_name}' (no known mapping and no "
                        f"usable 'repo_url' in its structure)."
                    ),
                }
            )
            continue

        actual_version, error = await asyncio.to_thread(
            _fetch_version_sync, repo, candidate_paths
        )

        if actual_version is None:
            results.append(
                {
                    "component": component_name,
                    "graph_version": graph_version,
                    "actual_version": None,
                    "status": "fetch_failed",
                    "message": error,
                }
            )
            continue

        results.append(
            {
                "component": component_name,
                "graph_version": graph_version,
                "actual_version": actual_version,
                "status": _compare_versions(graph_version, actual_version),
            }
        )

    return {"found": True, "components": results}