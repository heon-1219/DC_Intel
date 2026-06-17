from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import sentiment_logs as sl_repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.sentiment.pipeline import aggregate_sentiment

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class FakeClassifier:
    """Keyword stub standing in for mDeBERTa (offline)."""
    def classify_one(self, text):
        t = text.lower()
        if "crash" in t or "sell" in t:
            return "bearish", 0.9
        if "moon" in t or "upside" in t or "good" in t:
            return "bullish", 0.9
        return "neutral", 0.5


@pytest.mark.asyncio
async def test_aggregate_sentiment_classifies_and_writes_log(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await mi_repo.insert_intel(con, source="reddit", author_handle="u/a",
                                   content_snippet="samsung to the moon, great upside",
                                   posted_at=_iso(NOW), stock_id=ref.id, credibility_score=80)
        await mi_repo.insert_intel(con, source="stocktwits", author_handle="@b",
                                   content_snippet="this will crash hard, sell now",
                                   posted_at=_iso(NOW - timedelta(hours=2)), stock_id=ref.id,
                                   credibility_score=60)

    n = await aggregate_sentiment(db, r, FakeClassifier(), now=NOW)
    assert n == 1   # only 005930 has intel; other active stocks skipped

    async with connect(db) as con:
        snap = await sl_repo.get_latest(con, ref.id)
        rows = await mi_repo.list_recent_by_stock(con, ref.id, "2026-06-01T00:00:00Z")
    assert snap is not None and snap["aggregate_sentiment_score"] is not None
    assert {row["sentiment"] for row in rows} == {"bullish", "bearish"}   # rows classified + persisted
    assert snap["source_breakdown"]["item_counts_by_source"] == {"reddit": 1, "stocktwits": 1}
    assert snap["source_breakdown"]["timeframe_scores"]["24h"]["item_count"] == 2


@pytest.mark.asyncio
async def test_aggregate_sentiment_skips_short_text(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        await mi_repo.insert_intel(con, source="reddit", author_handle="u/a",
                                   content_snippet="buy",   # < 10 chars -> dropped from aggregation
                                   posted_at=_iso(NOW), stock_id=ref.id)
    n = await aggregate_sentiment(db, r, FakeClassifier(), now=NOW)
    assert n == 0   # no aggregation-eligible items
