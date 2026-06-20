"""M6i: /dashboard/economic-calendar affects-your-stocks overlay (optional auth)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo


async def _insert_event(affected):
    et = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    async with connect(get_settings().sqlite_path) as con:
        await con.execute(
            "INSERT INTO economic_events (event_name, event_time, impact_level, country, "
            "event_type, provider, status, affected_stocks_json) VALUES (?,?,?,?,?,?,?,?)",
            ("US CPI", et, "high", "US", "us_cpi", "seed", "scheduled", json.dumps(affected)))
        await con.commit()


async def _register(c):
    r = await c.post("/auth/register", json={"email": "u@x.com", "password": "Tr0ubadour9x"})
    d = r.json()["data"]
    return d["user"]["id"], d["access_token"]


async def _hold(uid, sym="005930", exch="KRX"):
    async with connect(get_settings().sqlite_path) as con:
        s = await srepo.get_stock(con, sym, exch)
        await prepo.insert_prediction(con, user_id=uid, stock_id=s.id, timeframe="5d",
                                      direction="up", confidence=66, reasoning_json={},
                                      model_version="v", window_closes_at="2099-01-01T00:00:00Z")


def _event(body):
    return [e for e in body["data"]["events"] if e["title_en"] == "US CPI"][0]


@pytest.mark.asyncio
async def test_anonymous_affects_null(app_client):
    await _insert_event({"stocks": [{"symbol": "005930", "exchange": "KRX"}], "sectors": [], "indexes": []})
    async with app_client as c:
        r = await c.get("/dashboard/economic-calendar")
    ev = _event(r.json())
    assert ev["affects_your_stocks"] is None and ev["match_level"] is None


@pytest.mark.asyncio
async def test_invalid_token_401(app_client):
    async with app_client as c:
        r = await c.get("/dashboard/economic-calendar", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_stock_match_overlay(app_client):
    async with app_client as c:
        uid, tok = await _register(c)
        await _hold(uid)
        await _insert_event({"scope": "stock", "stocks": [{"symbol": "005930", "exchange": "KRX",
                            "relation": "direct"}], "sectors": [], "indexes": [], "history": None})
        r = await c.get("/dashboard/economic-calendar", headers={"Authorization": f"Bearer {tok}"})
    ev = _event(r.json())
    assert ev["affects_your_stocks"] is True and ev["match_level"] == "stock"
    assert ev["matched_symbols"] == ["005930:KRX"]


@pytest.mark.asyncio
async def test_market_match_overlay(app_client):
    async with app_client as c:
        uid, tok = await _register(c)
        await _hold(uid)                                # KRX holding -> KOSPI market
        await _insert_event({"scope": "macro", "stocks": [], "sectors": [],
                             "indexes": ["KOSPI"], "history": None})
        r = await c.get("/dashboard/economic-calendar", headers={"Authorization": f"Bearer {tok}"})
    ev = _event(r.json())
    assert ev["match_level"] == "market" and ev["matched_symbols"] == []


@pytest.mark.asyncio
async def test_logged_in_no_holdings_false_not_null(app_client):
    async with app_client as c:
        _, tok = await _register(c)                     # registered but holds nothing
        await _insert_event({"stocks": [{"symbol": "005930", "exchange": "KRX"}], "sectors": [], "indexes": []})
        r = await c.get("/dashboard/economic-calendar", headers={"Authorization": f"Bearer {tok}"})
    ev = _event(r.json())
    assert ev["affects_your_stocks"] is False and ev["match_level"] is None   # False (not null) when logged in
