from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import json
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import market_intel as repo
from app.db.seed import seed_stocks
from app.intel.maintenance import purge_old_intel, recompute_author_stats

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")

NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


async def _set_created_at(con, intel_id: int, created_at: str) -> None:
    # created_at has a DB default; override it explicitly so the test is deterministic.
    await con.execute("UPDATE market_intel SET created_at=? WHERE id=?", (created_at, intel_id))
    await con.commit()


@pytest.mark.asyncio
async def test_purge_deletes_old_keeps_recent(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        old = await repo.insert_intel(con, source="reddit", author_handle="u/old",
                                      content_snippet="old post", posted_at="2026-01-01T00:00:00Z")
        recent = await repo.insert_intel(con, source="reddit", author_handle="u/new",
                                         content_snippet="new post",
                                         posted_at="2026-06-16T00:00:00Z")
        # 120 days old -> beyond the 90-day retention; 1 day old -> kept.
        await _set_created_at(con, old, _iso(NOW - timedelta(days=120)))
        await _set_created_at(con, recent, _iso(NOW - timedelta(days=1)))

    deleted = await purge_old_intel(db, now=NOW)
    assert deleted == 1

    async with connect(db) as con:
        assert await repo.get_by_id(con, old) is None
        assert await repo.get_by_id(con, recent) is not None


@pytest.mark.asyncio
async def test_purge_respects_explicit_retention_days(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        mid = await repo.insert_intel(con, source="reddit", author_handle="u/mid",
                                      content_snippet="mid", posted_at="2026-05-01T00:00:00Z")
        await _set_created_at(con, mid, _iso(NOW - timedelta(days=10)))

    # 10-day-old row survives 90-day retention but is purged at 7-day retention.
    assert await purge_old_intel(db, now=NOW, retention_days=90) == 0
    assert await purge_old_intel(db, now=NOW, retention_days=7) == 1


@pytest.mark.asyncio
async def test_recompute_author_stats_resolved_and_confirmed(tmp_path):
    db = await _db(tmp_path)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # Author with three items >48h old: two confirmed, one not.
    old_posted = _iso(NOW - timedelta(hours=72))
    async with connect(db) as con:
        await repo.insert_intel(con, source="reddit", author_handle="u/star",
                                content_snippet="a", posted_at=old_posted, confirmed=1)
        await repo.insert_intel(con, source="reddit", author_handle="u/star",
                                content_snippet="b", posted_at=old_posted, confirmed=1)
        await repo.insert_intel(con, source="reddit", author_handle="u/star",
                                content_snippet="c", posted_at=old_posted, confirmed=0)

    written = await recompute_author_stats(db, redis, now=NOW)
    assert written == 1

    raw = await redis.get("intel:authorstats:reddit:u/star")
    assert json.loads(raw) == {"resolved": 3, "confirmed": 2}
    assert await redis.ttl("intel:authorstats:reddit:u/star") > 0


@pytest.mark.asyncio
async def test_recompute_author_stats_excludes_recent(tmp_path):
    db = await _db(tmp_path)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fresh = _iso(NOW - timedelta(hours=1))      # <48h -> not yet resolved
    old = _iso(NOW - timedelta(hours=72))       # >48h -> resolved
    async with connect(db) as con:
        await repo.insert_intel(con, source="twitter", author_handle="@fresh",
                                content_snippet="x", posted_at=fresh, confirmed=1)
        await repo.insert_intel(con, source="twitter", author_handle="@aged",
                                content_snippet="y", posted_at=old, confirmed=0)

    written = await recompute_author_stats(db, redis, now=NOW)
    assert written == 1                          # only the aged author
    assert await redis.get("intel:authorstats:twitter:@fresh") is None
    assert json.loads(await redis.get("intel:authorstats:twitter:@aged")) == {
        "resolved": 1, "confirmed": 0}
