"""Regression tests for the 6 confirmed findings from the M8 adversarial review."""
import json
from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import httpx
import pandas as pd
import pytest

from app.cache import redis as cache_redis
from app.core.logging import redact
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.jobs.dashboard_builder import build_trending

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)


def _redact(d):
    return redact(None, "info", d)


# ---- Fix 1+2: 500 INTERNAL carries X-Request-ID + never leaks the exception message ----

@pytest.mark.asyncio
async def test_500_carries_request_id_header_and_redacts(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")   # avoid the (absent) redis on this path
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()

    async def _boom(request):
        raise ValueError("kaboom-secret-detail")

    app.add_route("/__boom", _boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/__boom", headers={"X-Request-ID": "req_trace_me"})
    get_settings.cache_clear()
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL"
    assert "kaboom-secret-detail" not in r.text            # message never leaks (§10.3)
    assert r.headers.get("x-request-id") == "req_trace_me"  # header stamped on the 500 (§10.1)
    assert r.json()["error"]["request_id"] == "req_trace_me"


# ---- Fix 3: success-path X-RateLimit headers report the BINDING (user) limit ----

@pytest.mark.asyncio
async def test_success_headers_report_binding_user_limit(app_client, monkeypatch):
    monkeypatch.setattr("app.core.middleware.GLOBAL_USER_PER_MIN", 5)   # user binds (5 < 100 IP)
    async with app_client as c:
        reg = await c.post("/auth/register", json={"email": "b@x.com", "password": "Tr0ubadour9x"})
        token = reg.json()["data"]["access_token"]
        r = await c.get("/dashboard/market-intel", headers={"Authorization": f"Bearer {token}"})
    assert r.headers["x-ratelimit-limit"] == "5"            # not the IP's 100
    assert int(r.headers["x-ratelimit-remaining"]) <= 4


# ---- Fix 4: redact() recurses into nested dict/list, without mutating the caller's data ----

def test_redacts_nested_secrets_and_emails():
    out = _redact({"event": "x", "headers": {"authorization": "Bearer T"},
                   "payload": {"password": "p"}, "claims": {"email": "a@b.com"},
                   "items": [{"email": "c@d.com"}]})
    assert out["headers"]["authorization"] == "***"
    assert out["payload"]["password"] == "***"
    assert "a@b.com" not in json.dumps(out["claims"]) and "***@***" in json.dumps(out["claims"])
    assert "c@d.com" not in json.dumps(out["items"])


def test_redact_does_not_mutate_caller_data():
    src = {"event": "x", "payload": {"password": "p"}}
    _redact(src)
    assert src["payload"]["password"] == "p"   # original nested dict untouched


# ---- Fix 5: LIKE wildcards in the search query are escaped (no over-matching) ----

@pytest.mark.asyncio
async def test_search_like_wildcards_escaped(app_client):
    async with app_client as c:
        pct = await c.get("/stocks/search", params={"q": "%"})
        und = await c.get("/stocks/search", params={"q": "_"})
        plain = await c.get("/stocks/search", params={"q": "ppl"})
    assert pct.json()["data"]["results"] == []     # '%' is literal now -> matches nothing
    assert und.json()["data"]["results"] == []      # '_' is literal now -> matches nothing
    assert any("Apple" in g["company_name_en"] for g in plain.json()["data"]["results"])


# ---- Fix 6: trending badge pairs directional win-rate with the DIRECTIONAL count ----

class _FakeBars:
    async def fetch_bars(self, ref, interval):
        idx = pd.to_datetime(["2026-06-15T00:00:00Z"], utc=True)
        return pd.DataFrame({"close": [10.0]}, index=idx)


@pytest.mark.asyncio
async def test_trending_win_rate_uses_directional_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.repositories.accuracy.MIN_SAMPLE", 2)
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await r.set("px:quote:AAPL:NASDAQ", json.dumps(
        {"price": 110.0, "previous_close": 100.0, "volume": 5, "currency": "USD",
         "as_of": "2026-06-15T01:00:00Z", "source": "yfinance"}))

    async with connect(db) as con:
        await con.execute("INSERT INTO users (email, password_hash, preferred_language) "
                          "VALUES ('t@x.com','h','en')")
        await con.commit()
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")

        async def _graded(direction, window, correct):
            pid = await prepo.insert_prediction(
                con, user_id=1, stock_id=ref.id, timeframe="5d", direction=direction,
                confidence=60, reasoning_json={}, model_version="v", window_closes_at=window)
            await prepo.record_outcome(
                con, prediction_id=pid, actual_direction="up", actual_price_change_percent=1.0,
                marked_correct=correct, exit_price=1.0, high_impact_event_overlap=0,
                checked_at_iso="2026-06-15T02:00:00Z")

        await _graded("up", "2026-06-10T00:00:00Z", 1)        # directional, correct
        await _graded("up", "2026-06-11T00:00:00Z", 0)        # directional, wrong
        await _graded("neutral", "2026-06-12T00:00:00Z", 1)   # neutral -> graded_total only

    per_region = await build_trending(db, r, _FakeBars(), now=NOW)
    aapl = next(c for c in per_region["us"][0]["gainers"] if c["instrument"] == "AAPL:NASDAQ")
    assert aapl["n_closed"] == 2          # directional count (not graded_total 3)
    assert aapl["win_rate_pct"] == 50.0   # 1 of 2 directional correct
