"""Tests for ``cks_mcp.llm.redact``."""
from __future__ import annotations

from unittest.mock import patch

from cks_mcp.llm.redact import redact_secret, scrub_secrets


def test_redact_secret_empty():
    assert redact_secret("") == ""


def test_redact_secret_short_value_fully_masked():
    assert redact_secret("short1") == "[REDACTED]"


def test_redact_secret_long_value_keeps_only_prefix_suffix():
    redacted = redact_secret("sk-ant-abcdefghijklmnop9999")
    assert redacted == "sk-a...9999"
    assert "abcdefghijklmnop" not in redacted


def test_scrub_secrets_removes_configured_anthropic_key():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-supersecretvalue123"}):
        text = "Anthropic API returned HTTP 401: bad key sk-ant-supersecretvalue123 given"
        scrubbed = scrub_secrets(text)
        assert "sk-ant-supersecretvalue123" not in scrubbed
        assert "[REDACTED]" in scrubbed


def test_scrub_secrets_removes_configured_openai_key():
    with patch.dict("os.environ", {"CKS_OPENAI_API_KEY": "sk-openaisecret456"}):
        text = "error: Authorization: Bearer sk-openaisecret456"
        scrubbed = scrub_secrets(text)
        assert "sk-openaisecret456" not in scrubbed


def test_scrub_secrets_noop_when_no_secret_present():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-value"}, clear=True):
        text = "no secrets here at all"
        assert scrub_secrets(text) == text


def test_scrub_secrets_empty_text():
    assert scrub_secrets("") == ""


def test_scrub_secrets_unset_env_vars_no_error():
    with patch.dict("os.environ", {}, clear=True):
        assert scrub_secrets("some text") == "some text"
