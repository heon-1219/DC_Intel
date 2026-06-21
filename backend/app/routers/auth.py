"""Auth router (backend-design AUTH §4): POST /auth/register (auto-login) + POST /auth/login.
Register enforces the password policy (422); duplicate email -> 409. Login returns the SAME
401 INVALID_CREDENTIALS for unknown-email and wrong-password, and runs bcrypt verify against a
dummy hash on unknown email to equalize timing (no user-enumeration via response time)."""
import functools
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.auth import ratelimit as rl
from app.auth.models import LoginRequest, RegisterRequest, serialize_user
from app.auth.security import encode_token, hash_password, verify_password
from app.cache import redis as cache_redis
from app.cache.redis import make_envelope
from app.config import get_settings
from app.core import errors
from app.core import logging as applog
from app.db.connection import connect
from app.db.repositories import users as urepo

router = APIRouter()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _err(status, code, en, ko, rid, details=None):
    return errors.error_json(status, code, en, ko, rid, details)


@functools.lru_cache
def _dummy_hash() -> str:
    """A real bcrypt hash (same cost) to verify against on unknown-email logins (timing defense)."""
    return hash_password("not-a-real-password-timing-x9")


def _auth_envelope(user_row, rid, status):
    now = datetime.now(timezone.utc)
    data = {
        "user": serialize_user(user_row),
        "access_token": encode_token(user_row["id"], now),
        "token_type": "bearer",
        "expires_in": get_settings().jwt_expiry_min * 60,
    }
    env = make_envelope(data, source="internal", data_as_of=_iso(now), is_stale=False,
                        cache="none", request_id=rid)
    return JSONResponse(status_code=status, content=env)


def _validation_details(exc: ValidationError) -> dict:
    return {"fields": [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                       for e in exc.errors()]}


async def _parse(request: Request, model):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON
        body = None
    if not isinstance(body, dict):
        raise ValidationError.from_exception_data("body", [])  # -> generic 422
    return model(**body)


@router.post("/auth/register")
async def register(request: Request):
    rid = errors.request_id(request)
    redis = cache_redis.get_client()
    allowed, _, retry = await rl.hit(redis, "register_ip", rl.client_ip(request),
                                     limit=5, window_sec=3600)
    if not allowed:
        return rl.rate_limited(rid, retry, 5)
    try:
        req = await _parse(request, RegisterRequest)
    except ValidationError as e:
        return _err(422, "VALIDATION_ERROR", "Check the form and try again.",
                    "입력값을 확인해 주세요.", rid, details=_validation_details(e))
    async with connect(get_settings().sqlite_path) as con:
        try:
            user = await urepo.create_user(con, req.email, hash_password(req.password), req.language)
        except sqlite3.IntegrityError:
            return _err(409, "EMAIL_TAKEN", "That email is already registered.",
                        "이미 가입된 이메일이에요.", rid)
    applog.get_logger().info("auth.register", user_id=user["id"], email=req.email)
    return _auth_envelope(user, rid, 201)


@router.post("/auth/login")
async def login(request: Request):
    rid = errors.request_id(request)
    try:
        req = await _parse(request, LoginRequest)
    except ValidationError as e:
        return _err(422, "VALIDATION_ERROR", "Check the form and try again.",
                    "입력값을 확인해 주세요.", rid, details=_validation_details(e))

    redis = cache_redis.get_client()
    ip, em = rl.client_ip(request), rl.sha1_email(req.email)
    b1, r1 = await rl.over_limit(redis, "login_ip", ip, limit=10, window_sec=900)
    b2, r2 = await rl.over_limit(redis, "login_email", em, limit=10, window_sec=900)
    if b1 or b2:
        return rl.rate_limited(rid, max(r1, r2), 10)

    async def _invalid():   # brute-force: count failed attempts (per-IP AND per-email)
        await rl.record_failure(redis, "login_ip", ip, window_sec=900)
        await rl.record_failure(redis, "login_email", em, window_sec=900)
        applog.get_logger().info("auth.login.failed", ip=ip, email_sha1=em[:12])
        return _err(401, "INVALID_CREDENTIALS", "Email or password is incorrect.",
                    "이메일 또는 비밀번호가 올바르지 않아요.", rid)

    async with connect(get_settings().sqlite_path) as con:
        user = await urepo.get_by_email(con, req.email)
    if user is None:
        verify_password(req.password, _dummy_hash())   # timing-equalize unknown email
        return await _invalid()
    if not verify_password(req.password, user["password_hash"]):
        return await _invalid()
    applog.get_logger().info("auth.login.success", user_id=user["id"])
    return _auth_envelope(user, rid, 200)
