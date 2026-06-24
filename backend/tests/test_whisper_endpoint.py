"""GET /stocks/{instrument}/whisper — read-only AIWCE result/abstention per stock (anonymous-ok)."""
from datetime import date, datetime, timezone

import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import stocks as srepo
from app.db.repositories import whisper as wrepo
from app.intel.whisper.models import WhisperResult


def _result(value=1.72, status="corroborated", reason=None, conf=80):
    return WhisperResult(
        whisper_value=value, confidence=conf, status=status, anchor=1.70,
        surprise_vs_anchor=(round(value - 1.70, 4) if value is not None else None),
        inlier_dispersion=0.01, n_inliers=3, n_outliers_rejected=1, n_distinct_families=3,
        contributing_families=("earningswhispers", "estimize", "websearch"),
        factors={"f_count": 1.0, "caps": []}, rounds_used=2, abstain_reason=reason,
        computed_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))


async def _seed_whisper(result, earnings_date=date(2026, 7, 1)):
    async with connect(get_settings().sqlite_path) as con:
        ref = await srepo.get_stock(con, "NVDA", "NASDAQ")
        await wrepo.upsert_result(con, stock_id=ref.id, earnings_event_id=None,
                                  earnings_date=earnings_date, result=result)


@pytest.mark.asyncio
async def test_whisper_endpoint_returns_corroborated(app_client):
    async with app_client as c:
        await _seed_whisper(_result())
        r = await c.get("/stocks/NVDA:NASDAQ/whisper")
    assert r.status_code == 200
    body = r.json()
    d = body["data"]
    assert d["instrument"] == "NVDA:NASDAQ"
    assert d["status"] == "corroborated"
    assert d["whisper_value"] == 1.72
    assert d["anchor"] == 1.70
    assert d["contributing_families"] == ["earningswhispers", "estimize", "websearch"]
    assert d["abstain_reason"] is None
    assert d["earnings_date"] == "2026-07-01"
    assert body["meta"]["request_id"]


@pytest.mark.asyncio
async def test_whisper_endpoint_returns_abstention(app_client):
    async with app_client as c:
        await _seed_whisper(_result(value=None, status="no_reliable_whisper",
                                    reason="NO_OBSERVATIONS", conf=0))
        r = await c.get("/stocks/NVDA:NASDAQ/whisper")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "no_reliable_whisper"
    assert d["whisper_value"] is None
    assert d["abstain_reason"] == "NO_OBSERVATIONS"


@pytest.mark.asyncio
async def test_whisper_endpoint_no_data_yet_is_200_with_none_status(app_client):
    # A seeded stock with no whisper row yet -> honest "not computed" envelope, not a 404.
    async with app_client as c:
        r = await c.get("/stocks/AAPL:NASDAQ/whisper")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["instrument"] == "AAPL:NASDAQ"
    assert d["status"] is None
    assert d["whisper_value"] is None


@pytest.mark.asyncio
async def test_whisper_endpoint_unknown_symbol_404(app_client):
    async with app_client as c:
        r = await c.get("/stocks/ZZZZ:NASDAQ/whisper")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SYMBOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_whisper_endpoint_bad_instrument_400(app_client):
    async with app_client as c:
        r = await c.get("/stocks/not-an-instrument/whisper")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PARAM"
