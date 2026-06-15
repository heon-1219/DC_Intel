"""econ_event_study nightly job (economic-calendar.md §8). For each event_type with an
upcoming occurrence, compute 1h/24h move stats over its past released occurrences (n>=4) for
each affected target, and write them into the upcoming occurrence's affected_stocks_json.history.

v1 target scope: affected indexes (via the index pseudo-row's yfinance ticker) + listed stocks
(via the stocks table). Sector proxies (SOXX etc., not in the stocks table) are a deferred
refinement. Reuses YFinanceBarProvider.fetch_bars(ref, '1h'). Inert until released history exists."""
import json
from datetime import datetime, timedelta, timezone

from app.calendar.event_study import aggregate, window_returns
from app.calendar.registry import load_registry
from app.db.connection import connect
from app.db.repositories import economic_events as repo
from app.db.repositories import stocks as srepo


def _surprise_sign(row: dict, registry: dict) -> int | None:
    avf = row.get("actual_vs_forecast_json")
    if not avf:
        return None
    try:
        m = json.loads(avf)["metrics"][0]
        s = m.get("surprise_abs")
        pol = int(json.loads(avf).get("surprise_polarity", 0) or 0)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    if s is None or not pol:
        return None
    return (1 if s > 0 else -1 if s < 0 else 0) * pol


def _targets(affected: dict) -> list[tuple[str, str, str]]:
    """Returns (target_id, lookup_key, kind). kind 'index' -> by symbol; 'stock' -> by sym:exch."""
    out = []
    for code in affected.get("indexes", []) or []:
        out.append((f"index:{code}", code, "index"))
    for s in affected.get("stocks", []) or []:
        key = f"{s['symbol']}:{s['exchange']}"
        out.append((f"stock:{key}", key, "stock"))
    return out


def _t0(row: dict) -> datetime:
    avf = row.get("actual_vs_forecast_json")
    if avf:
        try:
            ra = json.loads(avf).get("released_at_utc")
            if ra:
                return datetime.fromisoformat(ra.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))


async def econ_event_study(db_path: str, bars_provider, *, registry_path: str,
                           now: datetime | None = None, lookback_months: int = 24,
                           min_n: int = 4, horizon_days: int = 14) -> int:
    """Returns the number of upcoming occurrences whose history was written."""
    now = now or datetime.now(timezone.utc)
    registry = load_registry(registry_path)
    since = (now - timedelta(days=lookback_months * 30)).isoformat().replace("+00:00", "Z")

    async with connect(db_path) as con:
        stocks = await srepo.list_active_all(con)
        upcoming = await repo.list_in_range(
            con, now.isoformat().replace("+00:00", "Z"),
            (now + timedelta(days=horizon_days)).isoformat().replace("+00:00", "Z"))
    by_symbol = {s.symbol: s for s in stocks}
    by_key = {f"{s.symbol}:{s.exchange}": s for s in stocks}

    updated = 0
    for occ in upcoming:
        if not occ.get("affected_stocks_json"):
            continue
        affected = json.loads(occ["affected_stocks_json"])
        async with connect(db_path) as con:
            released = await repo.list_released_occurrences(con, occ["event_type"], since)
        if len(released) < min_n:
            continue
        signs = [_surprise_sign(r, registry) for r in released]
        t0s = [_t0(r) for r in released]

        per_target = []
        for tid, key, kind in _targets(affected):
            ref = by_symbol.get(key) if kind == "index" else by_key.get(key)
            if ref is None:
                continue
            try:
                bars = await bars_provider.fetch_bars(ref, "1h")
            except Exception:  # noqa: BLE001
                continue
            if bars is None or len(bars) == 0:
                continue
            stats = aggregate([window_returns(bars, t0) for t0 in t0s], signs)
            if stats:
                per_target.append({"target": tid, "windows": stats})

        if per_target:
            affected["history"] = {
                "lookback_months": lookback_months, "sample_size": len(released),
                "computed_at_utc": now.isoformat().replace("+00:00", "Z"),
                "per_target": per_target}
            async with connect(db_path) as con:
                await repo.update_history(con, occ["id"], affected)
            updated += 1
    return updated
