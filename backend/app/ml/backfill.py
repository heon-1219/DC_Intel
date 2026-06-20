"""Backfill historical technical_snapshots from real yfinance bars (prediction-model.md §7.1).

For each seed stock x feed interval we fetch the full available history and write ONE snapshot per
bar using the SAME compute_indicators math and the SAME timestamp format as the live recompute job
(indicator_pipeline._iso) — so backfilled and live snapshots are interchangeable and the dataset /
feature builder get dense as-of history (needed for rsi_slope_3 / macd_hist_delta neighbours and for
entry/exit close labels). Each bar's snapshot is computed over a trailing window (causal, capped at
WINDOW bars) so cost stays O(n * WINDOW) instead of O(n^2).

Sentiment/calendar are NOT backfilled (sentiment is forward-only) → those features are missing on
historical samples (the §4.4 path handles it). Run: python -m app.ml.backfill [--db PATH]."""
import argparse
import asyncio

from app.db.repositories import technical_snapshots as trepo
from app.providers.yfinance_bars import YFinanceBarProvider
from app.services.indicator_pipeline import _is_first_bar_of_session, _iso
from app.services.indicators import compute_indicators

WINDOW = 720        # trailing bars per compute (covers EMA200 + 3x convergence + squeeze 140)
START_MIN = 20      # skip the first ~20 bars (RSI/EMA not yet meaningful)

# Max yfinance history per interval (5m/15m <= 60d, 1h <= 730d, 1d effectively unbounded).
BACKFILL_DAYS = {"5m": 59, "15m": 59, "1h": 729, "1d": 1100}
INTERVALS = ("5m", "15m", "1h", "1d")


async def backfill_bars(con, ref, interval: str, bars_df, *, window: int = WINDOW,
                        start_min: int = START_MIN) -> int:
    """Compute + upsert one snapshot per bar from a (oldest->newest, UTC-indexed) OHLCV frame.
    Returns the number of snapshots written."""
    n = len(bars_df)
    written = 0
    for t in range(start_min, n):
        w = bars_df.iloc[max(0, t - window + 1): t + 1]
        payload = compute_indicators(w, bar_interval=interval,
                                     first_bar_of_session=_is_first_bar_of_session(w, interval))
        await trepo.upsert_snapshot(con, ref.id, interval, _iso(bars_df.index[t]), payload)
        written += 1
    return written


async def _fetch_history(ticker: str, interval: str, days: int):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return await asyncio.to_thread(YFinanceBarProvider._fetch, ticker, interval, days, now)


async def backfill_stock(con, ref, interval: str) -> int:
    """Live: fetch real yfinance history for one (stock, interval) and backfill its snapshots."""
    bars = await _fetch_history(ref.yfinance_ticker, interval, BACKFILL_DAYS[interval])
    if bars is None or len(bars) == 0:
        return 0
    return await backfill_bars(con, ref, interval, bars)


async def _run(db: str, intervals):
    from app.db.connection import connect
    from app.db.repositories import stocks as srepo
    async with connect(db) as con:
        refs = [r for r in await srepo.list_active_all(con) if r.exchange != "INDEX"]
        for ref in refs:
            for interval in intervals:
                try:
                    w = await backfill_stock(con, ref, interval)
                    print(f"{ref.symbol}:{ref.exchange} {interval}: {w} snapshots")
                except Exception as e:  # noqa: BLE001 - best-effort per (stock, interval)
                    print(f"{ref.symbol}:{ref.exchange} {interval}: FAILED {type(e).__name__}: {e}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Backfill technical_snapshots from real yfinance history.")
    p.add_argument("--db", default="dcintel.db")
    p.add_argument("--intervals", default=",".join(INTERVALS),
                   help="comma-separated subset of 5m,15m,1h,1d")
    a = p.parse_args(argv)
    asyncio.run(_run(a.db, tuple(a.intervals.split(","))))


if __name__ == "__main__":
    main()
