"""Redis fixed-window rate limiting (backend-design AUTH §5). v1 ships the SECURITY-BINDING
throttles — login brute-force (per-IP + per-email), register abuse, predict per-user — wired into
those routers. The global per-IP/per-user middleware is deferred to M10. FAIL-OPEN: a Redis outage
never blocks a request. Respects config.rate_limit_enabled. `now` is injectable for tests."""
import hashlib
import time

from fastapi.responses import JSONResponse

from app.config import get_settings


def sha1_email(email: str) -> str:
    return hashlib.sha1(email.lower().encode("utf-8")).hexdigest()


def client_ip(request) -> str:
    s = get_settings()
    if s.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Take the RIGHT-MOST hop — the one our single trusted front door (Caddy) appended.
            # The left tokens are client-supplied and spoofable, so trusting [0] would let an
            # attacker forge their IP and dodge the per-IP limit.
            return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _window_key(scope: str, ident: str, window_sec: int, now: float) -> tuple[str, int]:
    return f"rl:{scope}:{ident}:{int(now) // window_sec}", window_sec - (int(now) % window_sec)


async def hit(redis, scope: str, ident: str, *, limit: int, window_sec: int,
              now: float | None = None) -> tuple[bool, int, int]:
    """Count this request; returns (allowed, remaining, retry_after_sec). Blocks when count > limit.
    Use for all-request limits (predict, register)."""
    if not get_settings().rate_limit_enabled:
        return True, limit, 0
    t = time.time() if now is None else now
    key, retry = _window_key(scope, ident, window_sec, t)
    try:
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, window_sec)
    except Exception:   # noqa: BLE001 - fail-open
        return True, limit, 0
    if n > limit:
        return False, 0, retry
    return True, max(0, limit - n), 0


async def over_limit(redis, scope: str, ident: str, *, limit: int, window_sec: int,
                     now: float | None = None) -> tuple[bool, int]:
    """Peek (no increment): is the recorded count already at/over limit? Use to gate login on the
    failure counters BEFORE doing work. Returns (blocked, retry_after_sec)."""
    if not get_settings().rate_limit_enabled:
        return False, 0
    t = time.time() if now is None else now
    key, retry = _window_key(scope, ident, window_sec, t)
    try:
        raw = await redis.get(key)
        n = int(raw) if raw else 0
    except Exception:   # noqa: BLE001 - fail-open
        return False, 0
    return (n >= limit, retry) if n >= limit else (False, 0)


async def record_failure(redis, scope: str, ident: str, *, window_sec: int,
                         now: float | None = None) -> None:
    """Increment a failure counter (login). No-op on Redis failure."""
    if not get_settings().rate_limit_enabled:
        return
    t = time.time() if now is None else now
    key, _ = _window_key(scope, ident, window_sec, t)
    try:
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, window_sec)
    except Exception:   # noqa: BLE001 - fail-open
        pass


def rate_limited(rid: str, retry_after: int, limit: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(limit),
                 "X-RateLimit-Remaining": "0"},
        content={"error": {"code": "RATE_LIMITED",
                           "message_en": "Too many requests. Please slow down.",
                           "message_ko": "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
                           "details": {"retry_after": retry_after}, "request_id": rid}})
