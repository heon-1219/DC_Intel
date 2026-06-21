"""M8i — dash:* write-through builders (backend-design §5/§6.7/§6.8)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pandas as pd
import pytest

from app.db.migrate import migrate
from app.db.seed import seed_stocks
from app.jobs.dashboard_builder import build_indexes, build_trending

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)   # Monday 10:00 KST / 10:00 JST


class _FakeBars:
    async def fetch_bars(self, ref, interval):
        idx = pd.to_datetime(["2026-06-15T00:00:00Z", "2026-06-15T00:05:00Z"], utc=True)
        return pd.DataFrame({"close": [10.0, 11.0]}, index=idx)


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


async def _quote(r, symbol, exchange, price, pc, currency="USD"):
    await r.set(f"px:quote:{symbol}:{exchange}", json.dumps({
        "price": price, "previous_close": pc, "volume": 5, "day_high": price, "day_low": pc,
        "currency": currency, "as_of": "2026-06-15T01:00:00Z", "source": "yfinance"}))


@pytest.mark.asyncio
async def test_build_indexes_blob(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await _quote(r, "KOSPI", "INDEX", 2700.0, 2670.0, "KRW")
    out = await build_indexes(db, r, _FakeBars(), now=NOW)
    codes = {i["code"] for i in out}
    assert {"KOSPI", "NASDAQ_COMPOSITE", "SP500", "NIKKEI225", "DAX"} == codes
    kospi = next(i for i in out if i["code"] == "KOSPI")
    assert kospi["level"] == 2700.0 and kospi["change_pct"] == round(30 / 2670 * 100, 2)
    assert kospi["market_state"] == "open"          # KR session @ 10:00 KST
    assert kospi["sparkline"] == [10.0, 11.0]
    blob = json.loads(await r.get("dash:indexes"))
    assert len(blob["indexes"]) == 5 and blob["source"] == "yfinance"


@pytest.mark.asyncio
async def test_build_indexes_uncached_index_is_null_not_dropped(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    out = await build_indexes(db, r, _FakeBars(), now=NOW)   # no quotes seeded
    assert len(out) == 5
    assert all(i["level"] is None and i["change_pct"] is None for i in out)


@pytest.mark.asyncio
async def test_build_trending_ranks_gainers_and_losers(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await _quote(r, "AAPL", "NASDAQ", 110.0, 100.0)   # +10%
    await _quote(r, "MSFT", "NASDAQ", 95.0, 100.0)    # -5%
    await _quote(r, "NVDA", "NASDAQ", 102.0, 100.0)   # +2%
    per_region = await build_trending(db, r, _FakeBars(), now=NOW)
    us = per_region["us"][0]
    assert us["region"] == "us"
    g = [c["instrument"] for c in us["gainers"]]
    assert g[0] == "AAPL:NASDAQ" and g.index("AAPL:NASDAQ") < g.index("NVDA:NASDAQ")
    assert [c["instrument"] for c in us["losers"]] == ["MSFT:NASDAQ"]
    card = us["gainers"][0]
    assert card["change_pct"] == 10.0 and card["sparkline"] == [10.0, 11.0]
    assert card["win_rate_pct"] is None and card["n_closed"] == 0   # no graded outcomes yet


@pytest.mark.asyncio
async def test_build_trending_all_has_both_region_objects(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await _quote(r, "AAPL", "NASDAQ", 110.0, 100.0)
    await _quote(r, "005930", "KRX", 81000, 80000, "KRW")
    await build_trending(db, r, _FakeBars(), now=NOW)
    all_blob = json.loads(await r.get("dash:trending:all"))
    regions = {o["region"] for o in all_blob["regions"]}
    assert regions == {"kr", "us"}
    kr_obj = next(o for o in all_blob["regions"] if o["region"] == "kr")
    assert kr_obj["market_state"] == "open"   # KRX @ 10:00 KST
