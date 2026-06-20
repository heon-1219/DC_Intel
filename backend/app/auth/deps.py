"""Auth dependencies (backend-design AUTH §8-9). Token transport is the Authorization: Bearer
header ONLY. `resolve_user` is the testable core; the FastAPI deps wrap it with a DB connection.
AuthError is rendered as the standard 401 envelope by the handler registered in main.create_app.
Never log the Authorization header / token (AUTH §12)."""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.auth.security import decode_token
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import users as urepo


class AuthError(Exception):
    """Raised by the auth deps; the app handler turns it into a 401 UNAUTHORIZED envelope."""


def _extract_bearer(authorization: str | None) -> str:
    parts = (authorization or "").split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError()
    return parts[1].strip()


async def resolve_user(con, authorization: str | None, *, required: bool):
    """Required: missing/invalid -> AuthError. Optional: missing -> None, but PRESENT-but-invalid
    -> AuthError (AUTH §8). Returns the user row on success."""
    if authorization is None:
        if required:
            raise AuthError()
        return None
    token = _extract_bearer(authorization)        # present but malformed -> AuthError
    claims = decode_token(token)
    if not claims:
        raise AuthError()
    try:
        uid = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise AuthError()
    user = await urepo.get_by_id(con, uid)
    if user is None:
        raise AuthError()
    return user


async def get_current_user(request: Request):
    async with connect(get_settings().sqlite_path) as con:
        return await resolve_user(con, request.headers.get("authorization"), required=True)


async def get_current_user_optional(request: Request):
    async with connect(get_settings().sqlite_path) as con:
        return await resolve_user(con, request.headers.get("authorization"), required=False)


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    rid = request.headers.get("x-request-id", "req_local")
    return JSONResponse(status_code=401, content={"error": {
        "code": "UNAUTHORIZED", "message_en": "Sign in to continue.",
        "message_ko": "로그인이 필요해요.", "details": None, "request_id": rid}})
