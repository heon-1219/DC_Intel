"""Cross-cutting ASGI middleware (backend-design §10 request id, §4 global rate limit).

RequestIdMiddleware mints/honors a request id, exposes it on request.state + structlog contextvars,
and echoes it as the X-Request-ID response header. RateLimitMiddleware (M8c) enforces the §4.1 global
per-IP / per-user fixed-window limits."""
import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def new_request_id() -> str:
    return "req_" + secrets.token_hex(4)   # 'req_' + 8 hex (§10.1)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Set request.state.request_id (minted, or the inbound X-Request-ID), bind it into structlog
    contextvars for the duration of the request, and echo it on the response."""

    async def dispatch(self, request: Request, call_next):
        rid = (request.headers.get("x-request-id") or "")[:64] or new_request_id()
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = rid
        return response
