"""M8j — GET /dashboard/indexes + /dashboard/trending read endpoints (§6.7/§6.8)."""
import json

import pytest

from app.cache import redis as cache_redis


async def _set(key, value):
    await cache_redis.get_client().set(key, json.dumps(value))


def _index(code):
    return {"code": code, "name_en": code, "name_ko": code, "level": 100.0, "change": 1.0,
            "change_pct": 1.0, "market_state": "open", "sparkline": [1.0, 2.0],
            "data_as_of": "2026-06-15T01:00:00Z"}


def _card(inst, cp):
    return {"instrument": inst, "name_en": inst, "name_ko": inst, "price": 10.0, "currency": "USD",
            "change_pct": cp, "volume": 1, "sparkline": [1.0], "win_rate_pct": None, "n_closed": 0}


# ---------- indexes ----------

@pytest.mark.asyncio
async def test_indexes_returns_blob(app_client):
    async with app_client as c:
        await _set("dash:indexes", {"indexes": [_index("KOSPI"), _index("DAX")],
                                    "built_at": "2026-06-15T01:00:00Z", "source": "yfinance"})
        r = await c.get("/dashboard/indexes")
    assert r.status_code == 200
    body = r.json()
    assert [i["code"] for i in body["data"]["indexes"]] == ["KOSPI", "DAX"]
    assert body["meta"]["cache"] == "hit" and body["meta"]["is_stale"] is False


@pytest.mark.asyncio
async def test_indexes_cold_cache_is_empty_and_stale(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/indexes")
    body = r.json()
    assert r.status_code == 200 and body["data"]["indexes"] == []
    assert body["meta"]["cache"] == "miss" and body["meta"]["is_stale"] is True


@pytest.mark.asyncio
async def test_indexes_invalid_token_401(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/indexes", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


# ---------- trending ----------

@pytest.mark.asyncio
async def test_trending_returns_region_blob(app_client):
    blob = {"regions": [{"region": "us", "market_state": "open",
                         "gainers": [_card("AAPL:NASDAQ", 5.0)], "losers": [_card("MSFT:NASDAQ", -3.0)]}],
            "built_at": "2026-06-15T01:00:00Z", "source": "yfinance"}
    async with app_client as c:
        await _set("dash:trending:us", blob)
        r = await c.get("/dashboard/trending?region=us")
    body = r.json()
    assert r.status_code == 200
    assert body["data"]["regions"][0]["gainers"][0]["instrument"] == "AAPL:NASDAQ"
    assert body["meta"]["cache"] == "hit"


@pytest.mark.asyncio
async def test_trending_limit_slices_lists(app_client):
    cards = [_card(f"S{i}:NASDAQ", float(i)) for i in range(5)]
    blob = {"regions": [{"region": "us", "market_state": "open", "gainers": cards, "losers": []}],
            "built_at": "2026-06-15T01:00:00Z", "source": "yfinance"}
    async with app_client as c:
        await _set("dash:trending:us", blob)
        r = await c.get("/dashboard/trending?region=us&limit=2")
    assert len(r.json()["data"]["regions"][0]["gainers"]) == 2


@pytest.mark.asyncio
async def test_trending_bad_region_400(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/trending?region=eu")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAM"


@pytest.mark.asyncio
async def test_trending_cold_cache_empty(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/trending?region=all")
    body = r.json()
    assert r.status_code == 200 and body["data"]["regions"] == []
    assert body["meta"]["is_stale"] is True


@pytest.mark.asyncio
async def test_trending_invalid_token_401(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/trending", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401
