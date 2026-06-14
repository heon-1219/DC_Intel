from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import technical_snapshots as trepo
from app.providers.yfinance_bars import INTERVAL_SECONDS
from app.services.indicators import compute_indicators

INTERVALS = ("5m", "15m", "1h", "1d")
_SOURCE = "yfinance_bars"


def _is_first_bar_of_session(bars, interval: str) -> bool:
    """True if the last bar sits across a gap larger than one interval (a session open).
    Daily bars never count (the vol_z20 session-open guard is an intraday concern)."""
    if interval == "1d" or len(bars) < 2:
        return False
    gap = (bars.index[-1] - bars.index[-2]).total_seconds()
    return gap > 1.5 * INTERVAL_SECONDS[interval]


def _iso(ts) -> str:
    return ts.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def recompute_for_stock(db_path: str, ref, bars_provider, breaker, *,
                              now: datetime, intervals=INTERVALS) -> int:
    """Fetch bars -> compute_indicators -> upsert, per interval. Returns snapshots written.
    Single fetch attempt + circuit breaker (source 'yfinance_bars'), mirroring
    services/price.fetch_and_cache."""
    written = 0
    for interval in intervals:
        if await breaker.is_open(_SOURCE):
            continue
        try:
            bars = await bars_provider.fetch_bars(ref, interval)
        except Exception:  # noqa: BLE001 - providers normalize to ProviderError
            await breaker.record_failure(_SOURCE)
            continue
        await breaker.record_success(_SOURCE)
        if bars is None or len(bars) == 0:
            continue
        payload = compute_indicators(
            bars, bar_interval=interval,
            first_bar_of_session=_is_first_bar_of_session(bars, interval))
        ts = _iso(bars.index[-1])
        async with connect(db_path) as con:
            await trepo.upsert_snapshot(con, ref.id, interval, ts, payload)
        written += 1
    return written
