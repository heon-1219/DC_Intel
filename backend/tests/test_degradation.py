"""M8d — degradation matrix (backend-design §9.3/§9.4): the /predict price-staleness guard (unit)
+ degradation visibility (meta.source reflects the actual quote provider)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.cache import redis as cache_redis
from app.routers.predictions import price_is_degraded

NOW = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)


def _q(age_min):
    as_of = (NOW - timedelta(minutes=age_min)).isoformat().replace("+00:00", "Z")
    return {"price": 100.0, "as_of": as_of}


def test_degraded_when_open_and_stale():
    assert price_is_degraded("open", _q(45), NOW) is True


def test_not_degraded_when_open_and_fresh():
    assert price_is_degraded("open", _q(5), NOW) is False


def test_degraded_when_open_and_no_quote():
    assert price_is_degraded("open", None, NOW) is True


def test_not_degraded_when_closed_even_if_stale():
    assert price_is_degraded("closed", _q(600), NOW) is False
    assert price_is_degraded("closed", None, NOW) is False


@pytest.mark.asyncio
async def test_price_meta_source_reflects_fallback_provider(app_client):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    async with app_client as c:
        await cache_redis.get_client().set("px:quote:AAPL:NASDAQ", json.dumps(
            {"price": 195.0, "previous_close": 194.0, "volume": 1, "day_high": 196.0,
             "day_low": 193.0, "currency": "USD", "as_of": now, "source": "finnhub"}))
        r = await c.get("/stocks/AAPL:NASDAQ/price")
    assert r.status_code == 200
    assert r.json()["meta"]["source"] == "finnhub"   # fallback source surfaced (Yahoo-down row)
