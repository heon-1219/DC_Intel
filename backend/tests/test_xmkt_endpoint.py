import json

import pytest


async def _seed_cache(currency="KRW"):
    import app.cache.redis as cache_redis
    r = cache_redis.get_client()
    await r.set("px:fx:USDKRW", "1378.2")  # pre-cache FX so no network fetch in tests
    await r.set("px:quote:005930:KRX", json.dumps({
        "price": 84300.0, "previous_close": 83600.0, "volume": None, "day_high": None,
        "day_low": None, "currency": currency, "as_of": "2026-06-12T05:30:00Z",
        "source": "yfinance"}))
    return r


@pytest.mark.asyncio
async def test_prices_across_markets_single_listing(app_client):
    await _seed_cache()
    async with app_client as c:
        resp = await c.get("/stocks/005930:KRX/prices-across-markets")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["base_instrument"] == "005930:KRX"
    assert d["company_name_en"] == "Samsung Electronics"
    assert [x["instrument"] for x in d["listings"]] == ["005930:KRX"]
    assert d["listings"][0]["diff_pct_vs_base"] == 0.0
    assert d["fx_rates"]["USDKRW"] == 1378.2
    assert "note_ko" in d


@pytest.mark.asyncio
async def test_prices_across_markets_404_unknown(app_client):
    async with app_client as c:
        resp = await c.get("/stocks/ZZZZ:KRX/prices-across-markets")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_prices_across_markets_400_bad_instrument(app_client):
    async with app_client as c:
        resp = await c.get("/stocks/AAPL:FOO/prices-across-markets")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_price_endpoint_now_shows_real_names(app_client):
    await _seed_cache()
    async with app_client as c:
        resp = await c.get("/stocks/005930:KRX/price")
    d = resp.json()["data"]
    assert d["name_en"] == "Samsung Electronics" and d["name_ko"] == "삼성전자"
