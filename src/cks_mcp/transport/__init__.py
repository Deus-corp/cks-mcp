"""
HTTP transport for cks-mcp: optional bearer-token auth (``http_auth``),
the ``/events`` SSE endpoint's aiohttp wiring (``http_events``), and the
underlying SSE broadcaster (``sse``) that bridges the runtime's
``EventBus`` to HTTP subscribers.

Tool-call middleware (session validation, error normalization, ...) is
transport-agnostic -- it wraps handlers the same way regardless of
whether a request arrived over stdio or HTTP -- so it stays in
``cks_mcp.middleware``, not here.
"""
