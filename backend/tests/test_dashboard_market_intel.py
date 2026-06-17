import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo


async def _seed_intel(con, stock_id):
    await mi_repo.insert_intel(con, source="reddit", author_handle="u/a",
                               content_snippet="great upside on samsung, big news",
                               posted_at="2026-06-16T05:00:00Z", stock_id=stock_id,
                               cluster_id="cl_x", credibility_score=80, sentiment="bullish",
                               sentiment_confidence=0.9, confirmed=1)
    await mi_repo.insert_intel(con, source="twitter", author_handle="@b",
                               content_snippet="more samsung hype building",
                               posted_at="2026-06-16T05:01:00Z", stock_id=stock_id,
                               cluster_id="cl_x", credibility_score=70, sentiment="bullish",
                               sentiment_confidence=0.7)
    await mi_repo.insert_intel(con, source="naver", author_handle="익명",
                               content_snippet="low credibility noise post here",
                               posted_at="2026-06-16T05:02:00Z", stock_id=stock_id,
                               credibility_score=10)   # below default min_credibility 25


@pytest.mark.asyncio
async def test_market_intel_endpoint_clusters(app_client):
    async with connect(get_settings().sqlite_path) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_intel(con, ref.id)
    async with app_client as c:
        resp = await c.get("/dashboard/market-intel?stock=005930:KRX&lang=en")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["lang"] == "en" and d["anomalies"] == []
    clx = next(cl for cl in d["clusters"] if cl["cluster_id"] == "cl_x")
    assert clx["status"] == "CONFIRMED" and clx["badge"]["style"] == "confirmed"
    assert clx["sentiment"] == "bullish" and clx["item_count"] == 2
    assert clx["distinct_authors"] == 2 and clx["max_credibility"] == 80
    assert clx["credibility_band"] == "high" and clx["stock"]["symbol"] == "005930"
    assert all(cl["max_credibility"] >= 25 for cl in d["clusters"])   # cred-10 naver row filtered


@pytest.mark.asyncio
async def test_market_intel_korean_badge(app_client):
    async with connect(get_settings().sqlite_path) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed_intel(con, ref.id)
    async with app_client as c:
        resp = await c.get("/dashboard/market-intel?stock=005930:KRX&lang=ko")
    clx = next(cl for cl in resp.json()["data"]["clusters"] if cl["cluster_id"] == "cl_x")
    assert clx["badge"]["label"] == "확인됨"   # confirmed badge in Korean


@pytest.mark.asyncio
async def test_market_intel_validation_and_unknown(app_client):
    async with app_client as c:
        assert (await c.get("/dashboard/market-intel?limit=99")).status_code == 400
        assert (await c.get("/dashboard/market-intel?min_credibility=500")).status_code == 400
        assert (await c.get("/dashboard/market-intel?stock=AAPL:FOO")).status_code == 400
        assert (await c.get("/dashboard/market-intel?stock=ZZZZ:KRX")).status_code == 404
