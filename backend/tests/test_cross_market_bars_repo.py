"""M5d cross_market_bars repo — daily close series for reference instruments, as-of-bounded."""
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import cross_market_bars as repo

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    return db


@pytest.mark.asyncio
async def test_upsert_and_recent_closes_desc_bounded(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_bars(con, "SOXX", [("2026-06-08", 220.0), ("2026-06-09", 222.0),
                                             ("2026-06-10", 225.0), ("2026-06-11", 223.0)])
        rows = await repo.get_recent_closes(con, "SOXX", "2026-06-10", limit=2)
    assert rows == [("2026-06-10", 225.0), ("2026-06-09", 222.0)]   # <= max_date, newest first


@pytest.mark.asyncio
async def test_upsert_idempotent(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_bars(con, "SOXX", [("2026-06-10", 225.0)])
        await repo.upsert_bars(con, "SOXX", [("2026-06-10", 999.0)])   # overwrite same key
        rows = await repo.get_recent_closes(con, "SOXX", "2026-06-11", limit=10)
        cur = await con.execute("SELECT COUNT(*) c FROM cross_market_bars")
        n = (await cur.fetchone())["c"]
    assert n == 1 and rows == [("2026-06-10", 999.0)]


@pytest.mark.asyncio
async def test_recent_closes_isolated_by_ticker(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_bars(con, "SOXX", [("2026-06-10", 225.0)])
        await repo.upsert_bars(con, "^N225", [("2026-06-10", 39000.0)])
        soxx = await repo.get_recent_closes(con, "SOXX", "2026-06-11", limit=10)
    assert soxx == [("2026-06-10", 225.0)]   # ^N225 row not returned
