"""Event-study math (economic-calendar.md §8). Pure: given an hourly bar series and a set of
past release instants, compute the 1h/24h move statistics. The job (jobs/event_study.py) wires
this to real bars + released occurrences. v1 simplification: windows are bar-resolution and use
the bar series directly (the §8.3 'next session open' nuance for pre-market events is deferred)."""
from datetime import timedelta

_FLAT = 0.05   # |move| <= 0.05% counts as flat (excluded from direction consistency), §8.5


def window_returns(bars, t0) -> dict:
    """bars: DataFrame with a UTC DatetimeIndex and a 'close' column. Returns
    {'1h': pct|None, '24h': pct|None} relative to p0 = last close at/before t0."""
    idx = bars.index
    prior = bars[idx <= t0]
    if prior.empty:
        return {"1h": None, "24h": None}
    p0 = float(prior["close"].iloc[-1])
    if not p0:
        return {"1h": None, "24h": None}
    out = {}
    after_1h = bars[idx >= t0 + timedelta(hours=1)]
    p1 = float(after_1h["close"].iloc[0]) if not after_1h.empty else None
    out["1h"] = round((p1 - p0) / p0 * 100, 4) if p1 is not None else None
    within_24h = bars[(idx > t0) & (idx <= t0 + timedelta(hours=24))]
    p24 = float(within_24h["close"].iloc[-1]) if not within_24h.empty else None
    out["24h"] = round((p24 - p0) / p0 * 100, 4) if p24 is not None else None
    return out


def _mean(xs):
    return sum(xs) / len(xs)


def aggregate(returns_list: list[dict], surprise_signs: list[int | None]) -> dict:
    """Per-window §8.5 aggregates. surprise_signs[i] = sign(surprise_abs * polarity) for
    occurrence i (or None/0 when unknown)."""
    result = {}
    for w in ("1h", "24h"):
        pairs = [(r[w], s) for r, s in zip(returns_list, surprise_signs) if r.get(w) is not None]
        rs = [v for v, _ in pairs]
        if not rs:
            continue
        n_up = sum(1 for v in rs if v > _FLAT)
        n_down = sum(1 for v in rs if v < -_FLAT)
        denom = n_up + n_down
        consistency = round(max(n_up, n_down) / denom, 2) if denom else None
        modal = "up" if n_up > n_down else "down" if n_down > n_up else "mixed"
        aligned = [(v, s) for v, s in pairs if s]
        sac = (round(sum(1 for v, s in aligned
                         if (1 if v > 0 else -1 if v < 0 else 0) == s) / len(aligned), 2)
               if aligned else None)
        result[w] = {
            "n": len(rs),
            "avg_abs_move_pct": round(_mean([abs(v) for v in rs]), 2),
            "avg_signed_move_pct": round(_mean(rs), 2),
            "direction_consistency": consistency,
            "modal_direction": modal,
            "surprise_aligned_consistency": sac,
        }
    return result
