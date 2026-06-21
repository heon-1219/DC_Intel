"""M7e outcome-checker job (win-loss-tracking.md §5.4). Every minute: find matured ungraded
predictions, resolve each exit price (as-of the window close), grade with the snapshotted band, and
record the outcome atomically — deferring (retry backoff) when the exit bar isn't ready and parking
split-suspects / 8-times-failed rows. Prices are historical as-of lookups, so polling lag and a
backend-down gap grade the backlog identically. On each grade, the stock's accuracy cache is busted.

Run once: python -m app.jobs.outcome_checker [--db PATH]."""
import argparse
import asyncio
from datetime import datetime, timezone

from app.cache import redis as cache_redis
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.ml.config import load_ml_config
from app.tracking import retry as rt
from app.tracking.exit_price import resolve_exit_price
from app.tracking.grade import grade_prediction


async def _invalidate_accuracy(redis, ref) -> None:
    try:
        keys = [k async for k in redis.scan_iter(f"acc:{ref.symbol}:{ref.exchange}:*")]
        if keys:
            await redis.delete(*keys)
    except Exception:   # noqa: BLE001 - cache bust is best-effort
        pass


async def run_outcome_checker(db_path: str, redis, *, now=None) -> int:
    now_dt = now if isinstance(now, datetime) else (
        datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(timezone.utc))
    now_iso = now_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    now_epoch = now_dt.timestamp()
    bar_interval = load_ml_config()["bar_interval"]
    graded = 0
    async with connect(db_path) as con:
        due = await prepo.find_due(con, now_iso, limit=200)
        for d in due:
            pid = d["id"]
            if await rt.is_parked(redis, pid) or not await rt.due_for_retry(redis, pid, now_epoch):
                continue
            ref = await srepo.get_by_id(con, d["stock_id"])
            if ref is None:
                await rt.park(redis, pid, "unknown_stock")
                continue
            interval = bar_interval.get(d["timeframe"], "1d")
            price, status = await resolve_exit_price(con, redis, ref, d["window_closes_at"], interval)
            if status != "ok":
                n = await rt.record_attempt(redis, pid, now_epoch)
                if n >= rt.MAX_ATTEMPTS:
                    await rt.park(redis, pid, "max_retries")
                continue
            res = await grade_prediction(con, ref, d, price, now_iso)
            if res["action"] == "park":
                await rt.park(redis, pid, res["reason"])
                continue
            await prepo.record_outcome(con, prediction_id=pid, checked_at_iso=now_iso,
                                       **res["outcome"])
            await rt.clear_retry(redis, pid)
            await _invalidate_accuracy(redis, ref)
            graded += 1
    return graded


def _main(argv=None):
    p = argparse.ArgumentParser(description="Grade matured predictions into prediction_outcomes.")
    p.add_argument("--db", default=get_settings().sqlite_path)
    a = p.parse_args(argv)
    n = asyncio.run(run_outcome_checker(a.db, cache_redis.get_client()))
    print(f"graded {n}")


if __name__ == "__main__":
    _main()
