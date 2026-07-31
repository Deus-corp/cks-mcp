# Contributing to cks-mcp

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository.
2. Create a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
3. Install in editable mode: `pip install -e .[dev]`
4. Run tests: `python -m pytest -v`

Before opening a PR, also run the two checks CI enforces on every push —
passing tests alone isn't enough:

```bash
pip install ruff mypy types-requests
ruff check src/
mypy src/cks_mcp
```

## Adding a New Tool

A new tool touches exactly two places:

1. Its handler module in `src/cks_mcp/tools/` (or an existing module, if
   it belongs with related tools — e.g. `revert.py` holds both
   `list_versions` and `revert_version`).
2. Its entry in the `TOOLS` dict in `src/cks_mcp/tool_registry.py`
   (name, description, `inputSchema`, and the handler wired in).

Wrap the handler with `_wrap`, `_wrap_session`, or `_wrap_open_session`
(see `tool_registry.py`) rather than calling `log_tool_call()` directly —
this is what gives every tool its structured validation stack and
telemetry for free.

Once the tool works and is tested, add it to
[`docs/tools/`](docs/tools/index.md): pick the group file it fits best
(or start a new one), and add a row to the table in
[`docs/tools/index.md`](docs/tools/index.md) and to the
[README's tool table](README.md#available-tools). A tool without a
docs/tools/ entry is considered incomplete for review purposes.

## Pull Request Guidelines

- Keep PRs focused on a single feature or fix.
- Ensure all tests pass before submitting.
- Add tests for new functionality.
- Follow the existing code style.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).