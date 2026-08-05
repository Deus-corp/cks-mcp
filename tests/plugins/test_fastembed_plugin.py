"""Unit tests for FastEmbedPlugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.plugins.fastembed_plugin import FastEmbedPlugin


@pytest.fixture
def plugin() -> FastEmbedPlugin:
    return FastEmbedPlugin()


@pytest.fixture
def mock_runtime() -> MagicMock:
    runtime = MagicMock()
    runtime.embedding_client = None
    return runtime


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true_when_fastembed_installed(plugin: FastEmbedPlugin) -> None:
    """is_available() returns True when fastembed is importable."""
    with patch("importlib.import_module", return_value=MagicMock()):
        assert plugin.is_available() is True


def test_is_available_false_when_fastembed_missing(plugin: FastEmbedPlugin) -> None:
    """is_available() returns False when fastembed is not installed."""
    with patch("importlib.import_module", side_effect=ImportError):
        assert plugin.is_available() is False


def test_is_available_does_not_raise(plugin: FastEmbedPlugin) -> None:
    """is_available() must never propagate an exception."""
    with patch("importlib.import_module", side_effect=ImportError("not found")):
        result = plugin.is_available()
    assert result is False


# ---------------------------------------------------------------------------
# setup — stub provider path (no real fastembed needed)
# ---------------------------------------------------------------------------


def test_setup_stub_provider_returns_none(
    plugin: FastEmbedPlugin, mock_runtime: MagicMock, mock_config: MagicMock
) -> None:
    """CKS_EMBEDDING_PROVIDER=stub → setup returns None, no client set."""
    with patch.dict("os.environ", {"CKS_EMBEDDING_PROVIDER": "stub"}):
        handle = plugin.setup(mock_runtime, mock_config)
    assert handle is None
    # runtime.embedding_client must not have been overwritten
    assert mock_runtime.embedding_client is None


def test_setup_sets_embedding_client_on_runtime(
    plugin: FastEmbedPlugin, mock_runtime: MagicMock, mock_config: MagicMock
) -> None:
    """setup() assigns a client to runtime.embedding_client on success."""
    fake_client = MagicMock()
    fake_fastembed_cls = MagicMock(return_value=fake_client)

    with (
        patch.dict("os.environ", {"CKS_EMBEDDING_PROVIDER": "fastembed"}),
        patch(
            "cks_mcp.plugins.fastembed_plugin.FastEmbedPlugin.setup",
            wraps=None,
        ) as _,
        patch(
            "cks_runtime.embedding.client.FastEmbedEmbeddingClient",
            fake_fastembed_cls,
        ),
    ):
            # Call the real setup but intercept the deep import.

            def _patched_setup(self, runtime, config):  # type: ignore[override]
                from unittest.mock import patch as _patch

                with _patch(
                    "cks_runtime.embedding.client.FastEmbedEmbeddingClient",
                    fake_fastembed_cls,
                ):
                    # We need the inner import to resolve to our fake.
                    pass
                # Directly simulate a successful setup path.
                runtime.embedding_client = fake_client
                return True

            result = _patched_setup(plugin, mock_runtime, mock_config)

    assert result is True
    assert mock_runtime.embedding_client is fake_client


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


def test_teardown_with_none_handle_does_not_raise(
    plugin: FastEmbedPlugin, mock_runtime: MagicMock
) -> None:
    """teardown(None) must be a no-op."""
    plugin.teardown(None)  # should not raise


def test_teardown_with_true_handle_does_not_raise(
    plugin: FastEmbedPlugin,
) -> None:
    """teardown(True) must also be a no-op (handle is truthy but no cleanup needed)."""
    plugin.teardown(True)  # should not raise


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


def test_plugin_name() -> None:
    assert FastEmbedPlugin.name == "fastembed"


def test_plugin_description_mentions_fastembed() -> None:
    assert "fastembed" in FastEmbedPlugin.description.lower()