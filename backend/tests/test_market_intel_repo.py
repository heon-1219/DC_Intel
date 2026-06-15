from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_insert_defaults_and_readback(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        iid = await repo.insert_intel(
            con, source="reddit", author_handle="u/x", content_snippet="삼성 떡상 가즈아",
            posted_at="2026-06-16T05:00:00Z", stock_id=ref.id, url="https://r/x")
        row = await repo.get_by_id(con, iid)
    assert row["source"] == "reddit" and row["stock_id"] == ref.id
    assert row["credibility_score"] == 50          # schema default
    assert row["sentiment"] == "neutral" and row["confirmed"] == 0   # schema defaults
    assert row["cluster_id"] is None


@pytest.mark.asyncio
async def test_insert_with_overrides_and_list(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        await repo.insert_intel(con, source="twitter", author_handle="@a",
                                content_snippet="AAPL ripping", posted_at="2026-06-16T05:00:00Z",
                                stock_id=ref.id, credibility_score=82, sentiment="bullish",
                                sentiment_confidence=0.9, confirmed=1, cluster_id="cl_abc123")
        rows = await repo.list_recent_by_stock(con, ref.id, "2026-06-01T00:00:00Z")
    assert len(rows) == 1
    assert rows[0]["credibility_score"] == 82 and rows[0]["sentiment"] == "bullish"
    assert rows[0]["confirmed"] == 1 and rows[0]["cluster_id"] == "cl_abc123"


@pytest.mark.asyncio
async def test_market_wide_intel_null_stock(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        iid = await repo.insert_intel(con, source="newsapi", author_handle="reuters.com",
                                      content_snippet="Markets rally broadly",
                                      posted_at="2026-06-16T05:00:00Z")
        row = await repo.get_by_id(con, iid)
    assert row["stock_id"] is None   # market-wide
