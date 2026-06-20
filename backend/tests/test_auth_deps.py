"""M6c auth dependency core (backend-design AUTH §8). resolve_user is the testable heart of the
required/optional FastAPI deps: required -> 401 without/invalid token; optional -> anonymous OK but a
PRESENT-but-invalid token still -> 401."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.auth.deps import AuthError, resolve_user
from app.auth.security import encode_token
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import users as urepo

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


async def _db_with_user(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    async with connect(db) as con:
        u = await urepo.create_user(con, "u@x.com", "h", "en")
    return db, u["id"]


def _bearer(uid, *, now=None):
    return f"Bearer {encode_token(uid, now or datetime.now(timezone.utc))}"


@pytest.mark.asyncio
async def test_required_no_header_raises(tmp_path):
    db, _ = await _db_with_user(tmp_path)
    async with connect(db) as con:
        with pytest.raises(AuthError):
            await resolve_user(con, None, required=True)


@pytest.mark.asyncio
async def test_optional_no_header_returns_none(tmp_path):
    db, _ = await _db_with_user(tmp_path)
    async with connect(db) as con:
        assert await resolve_user(con, None, required=False) is None


@pytest.mark.asyncio
async def test_valid_token_returns_user(tmp_path):
    db, uid = await _db_with_user(tmp_path)
    async with connect(db) as con:
        user = await resolve_user(con, _bearer(uid), required=True)
    assert user["id"] == uid and user["email"] == "u@x.com"


@pytest.mark.asyncio
async def test_optional_present_but_invalid_raises(tmp_path):
    db, _ = await _db_with_user(tmp_path)
    async with connect(db) as con:
        with pytest.raises(AuthError):                       # AUTH §8: present+invalid -> 401 even optional
            await resolve_user(con, "Bearer garbage.token", required=False)


@pytest.mark.asyncio
async def test_malformed_scheme_raises(tmp_path):
    db, uid = await _db_with_user(tmp_path)
    async with connect(db) as con:
        with pytest.raises(AuthError):
            await resolve_user(con, "Token abc", required=True)


@pytest.mark.asyncio
async def test_expired_token_raises(tmp_path):
    db, uid = await _db_with_user(tmp_path)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    async with connect(db) as con:
        with pytest.raises(AuthError):
            await resolve_user(con, _bearer(uid, now=past), required=True)


@pytest.mark.asyncio
async def test_token_for_deleted_user_raises(tmp_path):
    db, _ = await _db_with_user(tmp_path)
    async with connect(db) as con:
        with pytest.raises(AuthError):
            await resolve_user(con, _bearer(999999), required=True)   # sub points to no user
