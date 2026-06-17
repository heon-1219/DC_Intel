"""aggregate_sentiment job (sentiment-pipeline.md §7, §10). For each active stock: classify its
recent market_intel items (zero-shot, cached), persist each item's sentiment, then compute the
six decay-weighted timeframe scores and write a sentiment_logs row. `classifier` is injected
(real ZeroShotClassifier in prod; a fake in tests) so the offline suite never loads weights."""
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import market_intel as mi_repo
from app.db.repositories import sentiment_logs as sl_repo
from app.db.repositories import stocks as srepo
from app.intel.config import SENTIMENT_ACTIVE_STOCK_CAP
from app.sentiment.aggregate import LOOKBACKS, aggregate
from app.sentiment.classify import classify_cached
from app.sentiment.normalize import normalize_for_classify

_MAX_LOOKBACK_H = max(LOOKBACKS.values())   # 120h — widest window we aggregate over


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def aggregate_sentiment(db_path: str, redis, classifier, *, now: datetime | None = None,
                              active_cap: int = SENTIMENT_ACTIVE_STOCK_CAP) -> int:
    """Returns the number of sentiment_logs rows written."""
    now = now or datetime.now(timezone.utc)
    since = _iso(now - timedelta(hours=_MAX_LOOKBACK_H))
    async with connect(db_path) as con:
        stocks = await srepo.list_active_all(con)

    written = 0
    for ref in stocks[:active_cap]:
        async with connect(db_path) as con:
            rows = await mi_repo.list_recent_by_stock(con, ref.id, since)
        items = []
        for r in rows:
            norm = normalize_for_classify(r["content_snippet"])
            if norm is None:
                continue
            weak = None   # StockTwits weak tag isn't persisted on the row in v1
            label, conf = await classify_cached(redis, classifier, norm, weak_label=weak)
            async with connect(db_path) as con:
                await mi_repo.set_sentiment(con, r["id"], label, conf)
            items.append({
                "sentiment": label, "confidence": conf,
                "credibility": r["credibility_score"], "posted_at": _parse(r["posted_at"]),
                "source": r["source"], "market_intel_id": r["id"],
                "author_handle": r["author_handle"], "url": r["url"]})
        if not items:
            continue
        headline, breakdown = aggregate(items, now)
        async with connect(db_path) as con:
            await sl_repo.insert_log(con, ref.id, _iso(now), headline, breakdown)
        written += 1
    return written


def _main() -> None:
    import asyncio

    from app.cache import redis as cache_redis
    from app.sentiment.classify import ZeroShotClassifier

    async def _run() -> None:
        s = get_settings()
        r = cache_redis.get_client()
        n = await aggregate_sentiment(s.sqlite_path, r, ZeroShotClassifier())
        print(f"aggregate_sentiment wrote {n} sentiment_logs rows")
        await r.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    _main()
