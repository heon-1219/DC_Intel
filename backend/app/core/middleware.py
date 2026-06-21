"""Cross-cutting ASGI middleware (backend-design §10 request id, §4 global rate limit).

RequestIdMiddleware mints/honors a request id, exposes it on request.state + structlog contextvars,
and echoes it as the X-Request-ID response header. RateLimitMiddleware (M8c) enforces the §4.1 global
per-IP / per-user fixed-window limits."""
import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth import ratelimit as rl
from app.auth.security import decode_token
from app.cache import redis as cache_redis
from app.config import get_settings

# §4.1 global fixed-window limits (module constants so tests can dial them down).
GLOBAL_IP_PER_MIN = 100
GLOBAL_USER_PER_MIN = 120
WINDOW_SEC = 60
EXEMPT_PATHS = {"/healthz"}


def new_request_id() -> str:
    return "req_" + secrets.token_hex(4)   # 'req_' + 8 hex (§10.1)


def _bearer_sub(request: Request) -> str | None:
    """The JWT subject when a VALID bearer token is present, else None (never raises — auth-required
    routes do their own 401; the global limiter just skips the per-user counter for anon/invalid)."""
    auth = request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    claims = decode_token(parts[1].strip())
    sub = claims.get("sub") if claims else None
    return str(sub) if sub is not None else None


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """§4.1 global limiter: per-IP (100/min, always) + per-user (120/min, when a valid token is
    present). Either can trip → 429 RATE_LIMITED. X-RateLimit-Limit/Remaining on every limited
    response; Retry-After on the 429. Fail-open (rl.hit) + bypassed when rate_limit_enabled is False.
    Per-route overrides (search/login/register/predict) compose on top — stricter wins."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS or not get_settings().rate_limit_enabled:
            return await call_next(request)
        rid = getattr(request.state, "request_id", None) or "req_local"
        redis = cache_redis.get_client()
        ip = rl.client_ip(request)
        ok_ip, remaining, retry_ip = await rl.hit(
            redis, "ip", ip, limit=GLOBAL_IP_PER_MIN, window_sec=WINDOW_SEC)
        ok_user, user_remaining, retry_user = True, None, 0
        sub = _bearer_sub(request)
        if sub is not None:
            ok_user, user_remaining, retry_user = await rl.hit(
                redis, "user", sub, limit=GLOBAL_USER_PER_MIN, window_sec=WINDOW_SEC)
        if not ok_ip or not ok_user:
            limit = GLOBAL_IP_PER_MIN if not ok_ip else GLOBAL_USER_PER_MIN
            return rl.rate_limited(rid, max(retry_ip, retry_user), limit)
        response = await call_next(request)
        # Advertise the BINDING constraint (smallest remaining) so the success-path headers agree
        # with the 429 path's limit selection — for an authenticated user the per-user limit may bind.
        if user_remaining is not None and user_remaining < remaining:
            eff_limit, eff_remaining = GLOBAL_USER_PER_MIN, user_remaining
        else:
            eff_limit, eff_remaining = GLOBAL_IP_PER_MIN, remaining
        response.headers["X-RateLimit-Limit"] = str(eff_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(eff_remaining, 0))
        return response
