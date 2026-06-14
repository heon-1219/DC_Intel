import json
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from app.db.repositories.stocks import Listing
from app.services.xmkt import build_cross_market

NOW = datetime(2026, 6, 12, 5, 40, tzinfo=timezone.utc)


async def _set(r, sym, exch, price, pc, currency):
    await r.set(f"px:quote:{sym}:{exch}", json.dumps({
        "price": price, "previous_close": pc, "volume": None, "day_high": None,
        "day_low": None, "currency": currency, "as_of": "2026-06-12T05:30:00Z",
        "source": "yfinance"}))


@pytest.mark.asyncio
async def test_build_cross_market_normalizes_and_diffs():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await _set(r, "005930", "KRX", 84300.0, 83600.0, "KRW")
    await _set(r, "SSNLF", "OTC", 31.0, 30.5, "USD")
    listings = [Listing("005930:KRX", "005930", "KRX", "KRW", None),
                Listing("SSNLF:OTC", "SSNLF", "OTC", "USD", 0.5)]
    names = {"en": "Samsung Electronics", "ko": "삼성전자"}
    out = await build_cross_market("005930", "KRX", names, listings, r, 1378.2, NOW)

    assert out["base_instrument"] == "005930:KRX"
    assert out["fx_rates"]["USDKRW"] == 1378.2
    rows = {row["instrument"]: row for row in out["listings"]}
    assert rows["005930:KRX"]["normalized_usd"] == pytest.approx(61.17, abs=0.05)
    assert rows["005930:KRX"]["diff_pct_vs_base"] == 0.0
    assert rows["SSNLF:OTC"]["normalized_usd"] == 62.0           # 31.0 / 0.5
    assert rows["SSNLF:OTC"]["diff_pct_vs_base"] == pytest.approx(1.36, abs=0.05)
    assert rows["SSNLF:OTC"]["adr_ratio"] == "1 ADR = 0.5 share"


@pytest.mark.asyncio
async def test_missing_quote_yields_nulls():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await _set(r, "005930", "KRX", 84300.0, 83600.0, "KRW")  # SSNLF uncached
    listings = [Listing("005930:KRX", "005930", "KRX", "KRW", None),
                Listing("SSNLF:OTC", "SSNLF", "OTC", "USD", 0.5)]
    out = await build_cross_market("005930", "KRX", {"en": "S", "ko": "S"}, listings, r, 1378.2, NOW)
    rows = {row["instrument"]: row for row in out["listings"]}
    assert rows["SSNLF:OTC"]["price"] is None
    assert rows["SSNLF:OTC"]["normalized_usd"] is None
    assert rows["SSNLF:OTC"]["diff_pct_vs_base"] is None
