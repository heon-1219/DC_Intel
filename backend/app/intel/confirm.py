"""Confirmation matcher (market-intel-pipeline.md §8). Flips an unconfirmed social cluster to
confirmed when an official-news item for the same stock is semantically close to the cluster
centroid (cosine >= INTEL_CONFIRM_SIM) and passes the entity guard (same stock). News rows
(source finnhub/newsapi) are already in market_intel with cached embeddings (intel:emb:{id}),
so matching reuses those — no re-fetch."""
from datetime import datetime, timedelta, timezone

from app.db.connection import connect
from app.db.repositories import market_intel as mi_repo
from app.intel import cluster_store
from app.intel.config import INTEL_CONFIRM_SIM
from app.intel.embed import cosine, get_cached_embedding

_NEWS_SOURCES = ("finnhub", "newsapi")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def match_confirmations(db_path: str, redis, *, now: datetime | None = None,
                              sim: float = INTEL_CONFIRM_SIM, window_h: int = 48) -> int:
    """Returns the number of clusters flipped to confirmed this run."""
    now = now or datetime.now(timezone.utc)
    async with connect(db_path) as con:
        rows = await mi_repo.list_recent(con, _iso(now - timedelta(hours=window_h)), limit=2000)

    news = [r for r in rows if r["source"] in _NEWS_SOURCES]
    # group unconfirmed social clusters
    clusters: dict[str, list[dict]] = {}
    for r in rows:
        cid = r["cluster_id"]
        if cid and r["source"] not in _NEWS_SOURCES:
            clusters.setdefault(cid, []).append(r)

    confirmed = 0
    for cid, items in clusters.items():
        if any(it["confirmed"] for it in items):
            continue
        centroid = await cluster_store.get_centroid(redis, cid)
        if centroid is None:
            continue
        stock_id = items[0]["stock_id"]
        for nrow in news:
            if nrow["stock_id"] != stock_id:        # entity guard: same stock
                continue
            nemb = await get_cached_embedding(redis, nrow["id"])
            if nemb is None:
                continue
            if cosine(centroid, nemb) >= sim:
                async with connect(db_path) as con:
                    await mi_repo.flip_confirmed_by_cluster(con, cid)
                confirmed += 1
                break
    return confirmed
