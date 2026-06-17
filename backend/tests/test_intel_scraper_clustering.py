from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.intel import cluster_store
from app.intel.models import RawIntel
from app.intel.scraper import ingest
from tests._fakes import FakeEmbedder, FakeSourceFetcher

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
DT = datetime(2026, 6, 16, 5, 0, tzinfo=timezone.utc)


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_ingest_with_embedder_clusters_and_scores(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # two different-author $AAPL posts -> same fake vector -> one cluster, 2 distinct authors
    items = [
        RawIntel("reddit", "u/a", None, "$AAPL massive breakout incoming", DT, symbols=["AAPL"],
                 account_age_days=400, engagement=5000),
        RawIntel("stocktwits", "@b", None, "$AAPL ripping to new highs", DT, symbols=["AAPL"],
                 account_age_days=200, engagement=800),
    ]
    n = await ingest(db, r, [FakeSourceFetcher("x", items)], now=DT, embedder=FakeEmbedder())
    assert n == 2

    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        rows = await mi_repo.list_recent_by_stock(con, ref.id, "2026-06-01T00:00:00Z")
    cluster_ids = {row["cluster_id"] for row in rows}
    assert len(cluster_ids) == 1 and None not in cluster_ids        # both joined one cluster
    cid = next(iter(cluster_ids))
    assert cid.startswith("cl_")
    # credibility was computed (not the default 50); reddit tier 70 + corroboration(2 authors)=25
    assert all(row["credibility_score"] != 50 for row in rows)

    clusters = await cluster_store.get_active_clusters(r, ref.id)
    assert len(clusters) == 1 and clusters[0]["item_count"] == 2
    assert len(set(clusters[0]["authors"])) == 2


@pytest.mark.asyncio
async def test_ingest_without_embedder_is_m4a_behavior(tmp_path):
    db = await _db(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    items = [RawIntel("reddit", "u/a", None, "$AAPL news", DT, symbols=["AAPL"])]
    n = await ingest(db, r, [FakeSourceFetcher("x", items)], now=DT)   # no embedder
    assert n == 1
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        rows = await mi_repo.list_recent_by_stock(con, ref.id, "2026-06-01T00:00:00Z")
    assert rows[0]["cluster_id"] is None and rows[0]["credibility_score"] == 50   # defaults
