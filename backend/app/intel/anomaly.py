"""Social-anomaly scan (market-intel-pipeline.md §9). Detects an unexplained intraday price
move so the feed can surface a social explanation. A move counts as "unexplained" when there is
no high-impact economic event for the stock's relevant country within ±NEWS_QUIET minutes — i.e.
a calendar release already explains it, so no social digging is warranted. Cooldown dedups
repeated alerts on the same name, unless the move has at least doubled vs. the last alert.

Offline-testable: pure pct math + a scan that takes an injected bars_provider/redis/db_path.
Never raises through to the scheduler — per-stock errors are swallowed (best-effort)."""
import json
from datetime import datetime, timedelta, timezone

from app.db.connection import connect
from app.db.repositories import economic_events as ee_repo
from app.db.repositories import stocks as srepo
from app.intel.config import (
    INTEL_ANOMALY_COOLDOWN_MIN,
    INTEL_ANOMALY_NEWS_QUIET_MIN,
    INTEL_ANOMALY_PCT,
    INTEL_ANOMALY_WINDOW_MIN,
)

# KR-listed names are also moved by US macro (the SOXX/Nasdaq lead-in), so a US high-impact
# release explains a KR move too. US names are explained only by US events.
_RELEVANT_COUNTRIES = {"KR": ["KR", "US"], "US": ["US"]}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def pct_change_over_window(bars, window_min: int, now: datetime) -> float | None:
    """Percent change of `close` from (now - window_min) to now, using last-known bars.

    bars: a pandas DataFrame with a UTC DatetimeIndex and a 'close' column (app/providers
    yfinance_bars shape). p_now = last close at/<= now; p_then = last close at/<= now -
    window_min minutes. Returns (p_now - p_then) / p_then * 100, or None if either anchor is
    missing (not enough history) or p_then is zero.
    """
    if bars is None or len(bars) == 0 or "close" not in bars.columns:
        return None
    then = now - timedelta(minutes=window_min)
    now_slice = bars.loc[bars.index <= now, "close"]
    then_slice = bars.loc[bars.index <= then, "close"]
    if len(now_slice) == 0 or len(then_slice) == 0:
        return None
    p_now = float(now_slice.iloc[-1])
    p_then = float(then_slice.iloc[-1])
    if p_then == 0:
        return None
    return (p_now - p_then) / p_then * 100.0


async def _high_impact_event_near(con, *, countries: list[str], now: datetime) -> bool:
    """True iff a high-impact economic event for any relevant country falls within ±NEWS_QUIET
    minutes of `now` — meaning the move is already calendar-explained (suppress the anomaly)."""
    quiet = timedelta(minutes=INTEL_ANOMALY_NEWS_QUIET_MIN)
    rows = await ee_repo.list_in_range(
        con, _iso(now - quiet), _iso(now + quiet), impact=["high"], country=countries)
    return len(rows) > 0


async def _cooldown_prev_abs(redis, *, sym: str, exch: str, now: datetime) -> float | None:
    """Max |change_pct| among existing anomaly keys for {sym}:{exch} whose detected_at is within
    INTEL_ANOMALY_COOLDOWN_MIN of `now`. None if no key is in cooldown (clear to fire)."""
    cutoff = now - timedelta(minutes=INTEL_ANOMALY_COOLDOWN_MIN)
    best: float | None = None
    try:
        async for key in redis.scan_iter(match=f"intel:anomaly:{sym}:{exch}:*"):
            raw = await redis.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue
            detected = _parse_iso(payload.get("detected_at", ""))
            if detected is None or detected < cutoff:
                continue
            prev = abs(float(payload.get("change_pct", 0.0)))
            best = prev if best is None else max(best, prev)
    except Exception:  # noqa: BLE001 - cooldown lookup is best-effort; never block a scan
        return None
    return best


async def scan_anomalies(db_path: str, redis, bars_provider, *, now: datetime | None = None,
                         registry_unused=None) -> int:
    """Scan every active non-index KR/US stock for an unexplained intraday move and write an
    anomaly key per trigger. Returns the number of triggers fired this run.

    A stock triggers iff:
      * |pct change over INTEL_ANOMALY_WINDOW_MIN| >= INTEL_ANOMALY_PCT, AND
      * no high-impact economic event for its relevant country within ±NEWS_QUIET of now, AND
      * not in cooldown — UNLESS the move is >= 2x the last alert's |change_pct| (escalation).
    """
    now = now or datetime.now(timezone.utc)

    async with connect(db_path) as con:
        stocks = []
        for region in ("KR", "US"):
            stocks.extend(await srepo.list_active_by_region(con, region))

    triggers = 0
    for ref in stocks:
        try:
            bars = await bars_provider.fetch_bars(ref, "5m")
        except Exception:  # noqa: BLE001 - a flaky symbol must not abort the scan
            continue
        if bars is None or len(bars) == 0:
            continue

        change = pct_change_over_window(bars, INTEL_ANOMALY_WINDOW_MIN, now)
        if change is None or abs(change) < INTEL_ANOMALY_PCT:
            continue

        countries = _RELEVANT_COUNTRIES.get(ref.region, [ref.region])
        async with connect(db_path) as con:
            if await _high_impact_event_near(con, countries=countries, now=now):
                continue  # calendar already explains the move

        prev_abs = await _cooldown_prev_abs(
            redis, sym=ref.symbol, exch=ref.exchange, now=now)
        if prev_abs is not None and abs(change) < 2 * prev_abs:
            continue  # in cooldown and not a 2x escalation

        payload = {
            "direction": "up" if change >= 0 else "down",
            "change_pct": round(change, 2),
            "window_minutes": INTEL_ANOMALY_WINDOW_MIN,
            "detected_at": _iso(now),
            "stock": {"symbol": ref.symbol, "exchange": ref.exchange},
        }
        key = f"intel:anomaly:{ref.symbol}:{ref.exchange}:{int(now.timestamp())}"
        try:
            await redis.set(key, json.dumps(payload), ex=7 * 24 * 3600)
        except Exception:  # noqa: BLE001 - a redis write failure shouldn't abort the scan
            continue
        triggers += 1

    return triggers
