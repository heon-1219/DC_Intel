"""M7b exit-price resolver (win-loss §5.2): realized price at/after window close from the persisted
bar snapshot, with a live-quote fallback; 'pending' when no price at/after the close yet."""
import json
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.tracking.exit_price import resolve_exit_price

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


def _redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_uses_first_snapshot_at_or_after_close(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-25T06:30:00Z", {"close": 100.0})
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-26T06:30:00Z", {"close": 110.0})
        price, status = await resolve_exit_price(con, _redis(), ref, "2026-06-26T00:00:00Z", "1d")
    assert status == "ok" and price == 110.0      # first bar >= t_close, not the 06-25 bar before it


@pytest.mark.asyncio
async def test_quote_fallback_when_no_snapshot(tmp_path):
    db = await _db(tmp_path)
    r = _redis()
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await r.set("px:quote:005930:KRX", json.dumps({"price": 84300.0, "as_of": "2026-06-26T07:00:00Z"}))
        price, status = await resolve_exit_price(con, r, ref, "2026-06-26T00:00:00Z", "1d")
    assert status == "ok" and price == 84300.0


@pytest.mark.asyncio
async def test_pending_when_no_price_at_or_after_close(tmp_path):
    db = await _db(tmp_path)
    r = _redis()
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        # only a snapshot BEFORE t_close + a quote BEFORE t_close -> exit bar not ready -> pending
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-25T06:30:00Z", {"close": 100.0})
        await r.set("px:quote:005930:KRX", json.dumps({"price": 99.0, "as_of": "2026-06-25T07:00:00Z"}))
        price, status = await resolve_exit_price(con, r, ref, "2026-06-26T00:00:00Z", "1d")
    assert price is None and status == "pending"


@pytest.mark.asyncio
async def test_pending_when_nothing(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        price, status = await resolve_exit_price(con, _redis(), ref, "2026-06-26T00:00:00Z", "1d")
    assert price is None and status == "pending"
