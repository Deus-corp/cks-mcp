"""
Secret-redaction helpers for ``cks_mcp.llm.providers``.

Nothing in ``llm_providers`` intentionally logs a raw API key -- error
messages are built from static strings like "ANTHROPIC_API_KEY is not
set" plus the *response body an HTTP error returned*. The risk this
module guards against is indirect: a misbehaving/misconfigured
provider endpoint could echo request headers (including
``Authorization``/``x-api-key``) back in an error body, which would
then get truncated into a ``RuntimeError`` message and potentially
land in a log or a tool response. ``scrub_secrets`` defends against
that by stripping any configured secret's *value* out of arbitrary
text before it's used in an error message; ``redact_secret`` is for
call sites (e.g. diagnostics/status tools) that want to show a
key is configured without showing the key itself.
"""

from __future__ import annotations

import os

# Every environment variable that may hold provider credentials or a
# bearer token. Kept in one place so a new provider only needs to be
# added here to get redaction "for free" everywhere scrub_secrets is
# used.
SECRET_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "CKS_OPENAI_API_KEY",
    "CKS_HTTP_TOKEN",
)

_REDACTED_MARKER = "[REDACTED]"


def redact_secret(value: str) -> str:
    """Return a short, non-reversible stand-in for *value* safe to log
    or display (e.g. "sk-a...f8Gh a key is configured" style
    diagnostics). Never returns the original value. Short values (<=8
    chars, not enough to leave a useful/identifying fragment) collapse
    to a flat marker instead of a partial prefix/suffix."""
    if not value:
        return ""
    if len(value) <= 8:
        return _REDACTED_MARKER
    return f"{value[:4]}...{value[-4:]}"


def scrub_secrets(text: str) -> str:
    """Return *text* with every currently-configured secret env var's
    value replaced by a redaction marker, wherever it appears
    verbatim. Safe to call on arbitrary provider-returned text (e.g.
    an HTTP error body) before folding it into an exception message,
    a log line, or a telemetry record. A no-op for text containing no
    configured secret."""
    if not text:
        return text
    scrubbed = text
    for var in SECRET_ENV_VARS:
        value = os.environ.get(var, "")
        if value and value in scrubbed:
            scrubbed = scrubbed.replace(value, _REDACTED_MARKER)
    return scrubbed


__all__ = ["SECRET_ENV_VARS", "redact_secret", "scrub_secrets"]
