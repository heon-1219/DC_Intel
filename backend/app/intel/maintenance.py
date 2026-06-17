"""Intel maintenance jobs (market-intel-pipeline.md §6.2/§14): the author-stats cache that
feeds the credibility A-subscore, plus 90-day retention. Both jobs accept an injected `now`
for deterministic tests and use app.db.connection.connect (which does NOT autocommit)."""
import json
from datetime import datetime, timedelta, timezone

from app.db.connection import connect
from app.intel.config import INTEL_RETENTION_DAYS

# Author profile data only matters once items have aged past the cluster TTL (48h): by then a
# post has had time to be confirmed/refuted, so its outcome is "resolved" for the A-subscore.
_RESOLVE_AGE_H = 48
_AUTHORSTATS_TTL_S = 26 * 3600   # daily job runs every 24h; 26h leaves a 2h refresh overlap


def _iso(dt: datetime) -> str:
    """tz-aware UTC -> ISO-8601 with a trailing 'Z'."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def purge_old_intel(db_path: str, *, now: datetime | None = None,
                          retention_days: int | None = None) -> int:
    """Delete market_intel rows older than the retention window. Returns rows deleted."""
    now = now or datetime.now(timezone.utc)
    retention_days = INTEL_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = _iso(now - timedelta(days=retention_days))
    async with connect(db_path) as con:
        cur = await con.execute("DELETE FROM market_intel WHERE created_at < ?", (cutoff,))
        await con.commit()
        return cur.rowcount


async def recompute_author_stats(db_path: str, redis, *, now: datetime | None = None) -> int:
    """Refresh the per-author confirmation cache used by the credibility A-subscore.

    For each (source, author_handle) with at least one market_intel row whose posted_at is older
    than 48h, count those resolved rows and how many were confirmed, and store the pair under
    `intel:authorstats:{source}:{handle}` (JSON, 26h TTL). Returns the number of authors written.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = _iso(now - timedelta(hours=_RESOLVE_AGE_H))
    async with connect(db_path) as con:
        cur = await con.execute(
            "SELECT source, author_handle, COUNT(*) AS resolved, "
            "       SUM(CASE WHEN confirmed = 1 THEN 1 ELSE 0 END) AS confirmed "
            "FROM market_intel WHERE posted_at < ? "
            "GROUP BY source, author_handle",
            (cutoff,))
        rows = await cur.fetchall()

    n = 0
    for r in rows:
        payload = json.dumps({"resolved": r["resolved"], "confirmed": r["confirmed"] or 0})
        await redis.set(f"intel:authorstats:{r['source']}:{r['author_handle']}", payload,
                        ex=_AUTHORSTATS_TTL_S)
        n += 1
    return n
