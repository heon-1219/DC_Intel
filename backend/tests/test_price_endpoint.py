import json

import pytest


@pytest.mark.asyncio
async def test_price_returns_cached_quote(app_client):
    import app.cache.redis as cache_redis
    await cache_redis.get_client().set("px:quote:005930:KRX", json.dumps({
        "price": 84300.0, "previous_close": 83600.0, "volume": 11250300,
        "day_high": 84600.0, "day_low": 83400.0, "currency": "KRW",
        "as_of": "2026-06-12T05:30:45Z", "source": "yfinance"}))
    async with app_client as c:
        r = await c.get("/stocks/005930:KRX/price")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["instrument"] == "005930:KRX" and d["price"] == 84300.0
    assert d["change"] == 700.0 and round(d["change_pct"], 2) == 0.84
    assert d["currency"] == "KRW" and d["market_state"] in {"open", "closed", "pre", "post"}
    assert r.json()["meta"]["source"] == "yfinance"


@pytest.mark.asyncio
async def test_price_404_when_unknown_symbol(app_client):
    async with app_client as c:
        r = await c.get("/stocks/ZZZZ:KRX/price")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_price_400_on_bad_instrument(app_client):
    async with app_client as c:
        r = await c.get("/stocks/AAPL:FOO/price")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_price_404_when_known_symbol_no_quote_yet(app_client):
    async with app_client as c:
        r = await c.get("/stocks/000660:KRX/price")  # seeded but no cached quote
    assert r.status_code == 404
