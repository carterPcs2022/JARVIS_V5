"""jarvis_mcp_server/auth.py — bearer-token gate for the Streamable HTTP
transport.

Reuses JARVIS_API_TOKEN exactly the way utils/security.py's verify_token()
already does for the main FastAPI app: same env var, same constant-time
comparison, same "empty token = open access" convention for local/dev use.
Deliberately not a second auth system.
"""
from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse

API_TOKEN = os.getenv("JARVIS_API_TOKEN", "")


class BearerAuthMiddleware:
    """Raw ASGI middleware (not Starlette's BaseHTTPMiddleware) so it never
    buffers the response body. Streamable HTTP responses are chunked/
    event-stream based; BaseHTTPMiddleware's request/response wrapping
    would break that.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not API_TOKEN:
            # Matches utils/security.py's convention: an unset
            # JARVIS_API_TOKEN means open access. Fine for local dev — set
            # the token before exposing this server to the internet.
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        provided = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""

        if not provided or not hmac.compare_digest(provided, API_TOKEN):
            response = JSONResponse(
                {"error": "Unauthorized — missing or invalid bearer token"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
