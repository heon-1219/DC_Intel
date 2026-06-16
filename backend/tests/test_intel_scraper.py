from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.intel.models import RawIntel
from app.intel.scraper import ingest
from app.providers.retry import ProviderError
from tests._fakes import FakeSourceFetcher

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
DT = datetime(2026, 6, 16, 5, 0, tzinfo=timezone.utc)


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_ingest_resolves_dedups_and_skips_disabled(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    items = [
        RawIntel("stocktwits", "@a", None, "$AAPL to the moon", DT, symbols=["AAPL"]),
        RawIntel("reddit", "u/b", None, "삼성전자 떡상 간다 $삼성전자", DT, symbols=["삼성전자"]),
        RawIntel("twitter", "@c", None, "$AAPL to the moon", DT, symbols=["AAPL"]),  # exact dup of #1
    ]
    fetcher = FakeSourceFetcher("live", items)
    off = FakeSourceFetcher("off", [RawIntel("reddit", "u/z", None, "ignored", DT)], enabled=False)
    boom = FakeSourceFetcher("boom", error=ProviderError("down"))

    n = await ingest(db, r, [fetcher, off, boom], now=DT)
    assert n == 2   # #3 is an exact duplicate of #1; disabled + erroring sources contribute nothing

    async with connect(db) as con:
        aapl = await srepo.get_stock(con, "AAPL", "NASDAQ")
        sams = await srepo.get_stock(con, "005930", "KRX")
        aapl_rows = await mi_repo.list_recent_by_stock(con, aapl.id, "2026-06-01T00:00:00Z")
        sams_rows = await mi_repo.list_recent_by_stock(con, sams.id, "2026-06-01T00:00:00Z")
    assert len(aapl_rows) == 1 and aapl_rows[0]["source"] == "stocktwits"     # cashtag -> stock_id
    assert len(sams_rows) == 1 and sams_rows[0]["source"] == "reddit"          # ko name -> stock_id


@pytest.mark.asyncio
async def test_ingest_market_wide_when_no_known_symbol(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    items = [RawIntel("reddit", "u/x", None, "the whole market is ripping today", DT)]
    n = await ingest(db, r, [FakeSourceFetcher("live", items)], now=DT)
    assert n == 1
    async with connect(db) as con:
        cur = await con.execute("SELECT stock_id, content_snippet FROM market_intel")
        row = dict(await cur.fetchone())
    assert row["stock_id"] is None   # market-wide
