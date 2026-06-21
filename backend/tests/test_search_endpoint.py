"""M8h — GET /stocks/search (backend-design §6.3): grouped search + live price overlay."""
import json
from datetime import datetime, timezone

import pytest

from app.cache import redis as cache_redis


def _now_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _seed_quote(symbol, exchange, price, currency):
    r = cache_redis.get_client()
    await r.set(f"px:quote:{symbol}:{exchange}", json.dumps({
        "price": price, "previous_close": price, "volume": 1, "day_high": price,
        "day_low": price, "currency": currency, "as_of": _now_z(), "source": "yfinance"}))


@pytest.mark.asyncio
async def test_symbol_prefix_match(app_client):
    async with app_client as c:
        r = await c.get("/stocks/search?q=AAP")
    assert r.status_code == 200
    names = [g["company_name_en"] for g in r.json()["data"]["results"]]
    assert any("Apple" in n for n in names)


@pytest.mark.asyncio
async def test_english_substring_match(app_client):
    async with app_client as c:
        r = await c.get("/stocks/search?q=apple")
    assert any("Apple" in g["company_name_en"] for g in r.json()["data"]["results"])


@pytest.mark.asyncio
async def test_korean_substring_match(app_client):
    async with app_client as c:
        r = await c.get("/stocks/search?q=삼성")
    results = r.json()["data"]["results"]
    assert any(g["company_name_ko"] and "삼성" in g["company_name_ko"] for g in results)


@pytest.mark.asyncio
async def test_usd_overlay_primary_and_diff(app_client):
    async with app_client as c:
        await _seed_quote("AAPL", "NASDAQ", 195.5, "USD")
        r = await c.get("/stocks/search?q=AAPL")
    apple = next(g for g in r.json()["data"]["results"] if "Apple" in g["company_name_en"])
    lst = apple["listings"][0]
    assert lst["last_price"] == 195.5 and lst["fx_rate"] == 1.0
    assert lst["kind"] == "common" and lst["is_primary"] is True
    assert lst["diff_vs_primary_pct"] is None   # null on the primary listing


@pytest.mark.asyncio
async def test_krw_overlay_fx_rate(app_client):
    async with app_client as c:
        r0 = cache_redis.get_client()
        await r0.set("px:fx:USDKRW", "1350")
        await _seed_quote("005930", "KRX", 81000, "KRW")
        r = await c.get("/stocks/search?q=005930")
    s = next(g for g in r.json()["data"]["results"] if g["listings"][0]["symbol"] == "005930")
    lst = s["listings"][0]
    assert lst["last_price"] == 81000 and abs(lst["fx_rate"] - round(1 / 1350, 8)) < 1e-12


@pytest.mark.asyncio
async def test_empty_and_overlong_q_400(app_client):
    async with app_client as c:
        empty = await c.get("/stocks/search")
        overlong = await c.get("/stocks/search?q=" + "a" * 51)
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "INVALID_PARAM"
    assert overlong.status_code == 400


@pytest.mark.asyncio
async def test_metadata_cache_hit_on_repeat(app_client):
    async with app_client as c:
        a = await c.get("/stocks/search?q=apple")
        b = await c.get("/stocks/search?q=apple")
    assert a.json()["meta"]["cache"] == "miss"
    assert b.json()["meta"]["cache"] == "metadata-hit"


@pytest.mark.asyncio
async def test_per_route_rate_limit_429(app_client, monkeypatch):
    monkeypatch.setattr("app.routers.stocks.SEARCH_LIMIT_PER_MIN", 1)
    async with app_client as c:
        s1 = await c.get("/stocks/search?q=apple")
        s2 = await c.get("/stocks/search?q=apple")
    assert s1.status_code == 200 and s2.status_code == 429
    assert s2.json()["error"]["code"] == "RATE_LIMITED"
