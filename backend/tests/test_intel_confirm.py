import json
from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks
from app.intel.confirm import match_confirmations
from app.intel.embed import cache_embedding

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 16, 5, 0, tzinfo=timezone.utc)
ISO = "2026-06-16T05:00:00Z"


async def _setup(tmp_path, news_vec):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        await mi_repo.insert_intel(con, source="reddit", author_handle="u/a",
                                   content_snippet="AAPL big acquisition rumor", posted_at=ISO,
                                   stock_id=ref.id, cluster_id="cl_x", credibility_score=60)
        await mi_repo.insert_intel(con, source="twitter", author_handle="@b",
                                   content_snippet="AAPL acquiring something big", posted_at=ISO,
                                   stock_id=ref.id, cluster_id="cl_x", credibility_score=55)
        nid = await mi_repo.insert_intel(con, source="finnhub", author_handle="reuters.com",
                                         content_snippet="Apple announces acquisition", posted_at=ISO,
                                         stock_id=ref.id)
    await r.set("intel:cluster:cl_x", json.dumps(
        {"centroid": [1.0, 0.0, 0.0], "stock_id": ref.id, "item_count": 2,
         "authors": ["reddit:u/a", "twitter:@b"], "coordinated": False, "first_posted_at": ISO}))
    await cache_embedding(r, nid, news_vec)
    return db, r, ref.id


@pytest.mark.asyncio
async def test_confirmation_flips_cluster_on_news_match(tmp_path):
    db, r, sid = await _setup(tmp_path, news_vec=[1.0, 0.0, 0.0])   # aligned w/ centroid -> cos 1.0
    n = await match_confirmations(db, r, now=NOW)
    assert n == 1
    async with connect(db) as con:
        rows = await mi_repo.list_recent_by_stock(con, sid, "2026-06-01T00:00:00Z")
    social = [row for row in rows if row["cluster_id"] == "cl_x"]
    assert social and all(row["confirmed"] == 1 for row in social)   # whole cluster flips


@pytest.mark.asyncio
async def test_no_confirmation_when_dissimilar(tmp_path):
    db, r, sid = await _setup(tmp_path, news_vec=[0.0, 1.0, 0.0])   # orthogonal -> cos 0 < 0.70
    assert await match_confirmations(db, r, now=NOW) == 0
