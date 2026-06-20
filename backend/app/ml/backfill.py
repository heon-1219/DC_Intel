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

from app.db.repositories import cross_market_bars as cmrepo
from app.db.repositories import technical_snapshots as trepo
from app.ml.xmkt import resolve_reference
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


async def _backfill_with_retry(con, ref, interval, *, attempts: int, base_delay: float) -> int:
    """Retry a (stock, interval) fetch — yfinance (a free endpoint) rate-limits bursts, surfacing
    as empty results or transient connection errors. Exponential backoff; returns snapshots written."""
    last_err = None
    for attempt in range(attempts):
        try:
            w = await backfill_stock(con, ref, interval)
            if w > 0:
                return w
            last_err = "0 snapshots (empty/rate-limited)"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        if attempt < attempts - 1:
            await asyncio.sleep(base_delay * (attempt + 1))
    print(f"{ref.symbol}:{ref.exchange} {interval}: gave up after {attempts} - {last_err}")
    return 0


def distinct_references(stock_refs) -> list[str]:
    """The set of yfinance reference tickers to backfill, resolved from stocks.xmkt_reference
    (non-index stocks only). Pure + deterministic (sorted)."""
    return sorted({resolve_reference(s.xmkt_reference) for s in stock_refs if s.exchange != "INDEX"})


async def backfill_reference(con, ref_ticker: str, *, days: int = 1100) -> int:
    """Fetch a reference's real daily history from yfinance and store closes in cross_market_bars."""
    bars = await _fetch_history(ref_ticker, "1d", days)
    if bars is None or len(bars) == 0:
        return 0
    rows = [(idx.date().isoformat(), float(c))
            for idx, c in zip(bars.index, bars["close"]) if c == c]  # drop NaN closes
    await cmrepo.upsert_bars(con, ref_ticker, rows)
    return len(rows)


async def _backfill_references(con, *, delay_sec: float, attempts: int):
    from app.db.repositories import stocks as srepo
    refs = distinct_references(await srepo.list_active_all(con))
    for ref in refs:
        last = None
        for attempt in range(attempts):
            try:
                n = await backfill_reference(con, ref)
                if n > 0:
                    print(f"[ref] {ref}: {n} daily bars")
                    break
                last = "0 bars"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
            if attempt < attempts - 1:
                await asyncio.sleep(delay_sec * (attempt + 1))
        else:
            print(f"[ref] {ref}: gave up - {last}")
        await asyncio.sleep(delay_sec)


async def _run(db: str, intervals, *, delay_sec: float = 2.0, attempts: int = 4,
               refs_only: bool = False):
    from app.db.connection import connect
    from app.db.repositories import stocks as srepo
    async with connect(db) as con:
        if not refs_only:
            refs = [r for r in await srepo.list_active_all(con) if r.exchange != "INDEX"]
            for ref in refs:
                for interval in intervals:
                    w = await _backfill_with_retry(con, ref, interval, attempts=attempts,
                                                   base_delay=delay_sec)
                    if w:
                        print(f"{ref.symbol}:{ref.exchange} {interval}: {w} snapshots")
                    await asyncio.sleep(delay_sec)   # courtesy throttle between requests
        await _backfill_references(con, delay_sec=delay_sec, attempts=attempts)


def main(argv=None):
    p = argparse.ArgumentParser(description="Backfill technical_snapshots from real yfinance history.")
    p.add_argument("--db", default="dcintel.db")
    p.add_argument("--intervals", default=",".join(INTERVALS),
                   help="comma-separated subset of 5m,15m,1h,1d")
    p.add_argument("--refs-only", action="store_true",
                   help="skip per-stock snapshots; only backfill cross-market reference daily bars")
    a = p.parse_args(argv)
    asyncio.run(_run(a.db, tuple(a.intervals.split(",")), refs_only=a.refs_only))


if __name__ == "__main__":
    main()
