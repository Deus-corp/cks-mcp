"""
Optional bearer-token auth for cks-mcp's HTTP transport.

Controlled by the ``CKS_MCP_HTTP_TOKEN`` environment variable:

- If unset (or empty), auth is disabled and every request is allowed
  through unchanged -- this preserves the historical, no-auth behavior
  of the HTTP transport.
- If set, every request to a protected route must present the token,
  either as ``Authorization: Bearer <token>`` or as a ``?token=``
  query parameter. The latter exists because ``EventSource`` (used to
  consume the ``/events`` SSE endpoint from a browser) cannot set
  custom request headers.

The token is read from the environment once and cached at module
import time. This matches how the rest of cks-mcp treats
process-lifetime configuration (e.g. ``CKS_MCP_DB_PATH``) and avoids
re-reading the environment on every request.
"""

from __future__ import annotations

import hmac
import os

from aiohttp.web import Request

_AUTH_TOKEN_ENV_VAR = "CKS_MCP_HTTP_TOKEN"

# Cached once at import time -- see module docstring.
_CACHED_TOKEN: str | None = os.environ.get(_AUTH_TOKEN_ENV_VAR) or None


def is_auth_enabled() -> bool:
    """True if ``CKS_MCP_HTTP_TOKEN`` is set to a non-empty value."""
    return _CACHED_TOKEN is not None


def _extract_token(request: Request) -> str | None:
    """
    Pull a candidate token out of ``request``, preferring the
    ``Authorization`` header (case-insensitive ``Bearer`` prefix) and
    falling back to the ``token`` query parameter.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip()
            if candidate:
                return candidate

    query_token = request.query.get("token")
    if query_token:
        return query_token

    return None


def is_request_authorized(request: Request) -> bool:
    """
    True if auth is disabled, or if ``request`` carries a token that
    matches ``CKS_MCP_HTTP_TOKEN`` (compared in constant time).
    """
    if _CACHED_TOKEN is None:
        return True

    candidate = _extract_token(request)
    if not candidate:
        return False

    return hmac.compare_digest(candidate, _CACHED_TOKEN)
