"""M6b users repository (backend-design AUTH §6-7). Email stored + looked up lowercased; the
unique index makes duplicate registration an IntegrityError the router turns into 409."""
import sqlite3
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import users as repo

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    return db


@pytest.mark.asyncio
async def test_create_then_get_by_email_case_insensitive(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        created = await repo.create_user(con, "FOO@Example.com", "hash123", "en")
        found = await repo.get_by_email(con, "foo@example.com")
        also = await repo.get_by_email(con, "FOO@EXAMPLE.COM")
    assert created["email"] == "foo@example.com"          # stored lowercased
    assert created["preferred_language"] == "en"
    assert found["id"] == created["id"]
    assert also["id"] == created["id"]                     # NOCASE lookup


@pytest.mark.asyncio
async def test_duplicate_email_raises(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.create_user(con, "dup@x.com", "h", "en")
        with pytest.raises(sqlite3.IntegrityError):
            await repo.create_user(con, "DUP@x.com", "h2", "ko")   # same email, case-folded


@pytest.mark.asyncio
async def test_get_by_id_roundtrip_and_missing(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        u = await repo.create_user(con, "id@x.com", "h", "ko")
        got = await repo.get_by_id(con, u["id"])
        missing = await repo.get_by_id(con, 999999)
    assert got["email"] == "id@x.com" and got["preferred_language"] == "ko"
    assert got["password_hash"] == "h"      # repo returns the hash for login verification
    assert missing is None
