"""M7j operator backfill for PARKED predictions (win-loss-tracking.md §5.6). The only path allowed
to grade a parked row: runs the identical §5.4 grading math with an operator-supplied verified exit
price, bypassing the split-suspect guard, then records the outcome + unparks + clears retry + audits.
Refuses to double-grade an already-graded prediction (UNIQUE prediction_id).

Run: python -m app.tracking.backfill --prediction-id N --price P [--db PATH]."""
import argparse
import asyncio
import logging
from datetime import datetime, timezone

from app.cache import redis as cache_redis
from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.tracking import retry as rt
from app.tracking.grade import grade_prediction

_LOG = logging.getLogger("dcintel.outcome")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def backfill_one(db_path: str, redis, prediction_id: int, price: float,
                       *, now_iso: str | None = None) -> bool:
    """Grade one parked/ungraded prediction at the supplied exit price. Returns True if graded,
    False if unknown / already graded / ungradeable (no entry price)."""
    now_iso = now_iso or _iso(datetime.now(timezone.utc))
    async with connect(db_path) as con:
        row = await prepo.get_by_id(con, prediction_id)
        if row is None or row["checked_at"] is not None:
            return False                                  # unknown or already graded
        ref = await srepo.get_by_id(con, row["stock_id"])
        if ref is None:
            return False
        res = await grade_prediction(con, ref, row, price, now_iso, bypass_split=True)
        if res["action"] != "grade":
            return False
        await prepo.record_outcome(con, prediction_id=prediction_id, checked_at_iso=now_iso,
                                   **res["outcome"])
    await rt.unpark(redis, prediction_id)
    await rt.clear_retry(redis, prediction_id)
    _LOG.warning("outcome backfill: prediction=%s price=%s -> %s (operator override)",
                 prediction_id, price, res["outcome"]["actual_direction"])
    return True


def _main(argv=None):
    p = argparse.ArgumentParser(description="Operator backfill of a parked prediction's outcome.")
    p.add_argument("--prediction-id", type=int, required=True)
    p.add_argument("--price", type=float, required=True, help="verified exit price (listing currency)")
    p.add_argument("--db", default=get_settings().sqlite_path)
    a = p.parse_args(argv)
    ok = asyncio.run(backfill_one(a.db, cache_redis.get_client(), a.prediction_id, a.price))
    print("graded" if ok else "skipped (unknown / already graded / no entry price)")


if __name__ == "__main__":
    _main()
