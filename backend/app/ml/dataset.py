"""Assemble the training set (prediction-model.md §7.1/§7.3).

For each seed stock we walk its backfilled technical_snapshots (one per trading bar of the tf's
feed interval). At each entry bar (stepped by the horizon, so labels never overlap) we:
  * read entry/exit `close` straight from the snapshot payloads,
  * derive the realized 3-class label via the SHARED labels.derive_direction + dead-band,
  * build the feature vector with the SAME as-of-bounded builder used at serve time (train/serve
    parity — the #1 anti-leakage guard).

Window resolution: bar-count step (labels.HORIZON_BARS) for the regular-session (1h/5h) and
N-trading-day (2d/3d/5d) horizons — exact because the snapshot sequence holds only trading bars.
"24h" (same-time next trading day) has a variable session length, so it is resolved by wall-clock:
the first snapshot at/after entry + 24h. Sentiment is forward-only, so backfilled samples carry it
as missing (§4.4 path) — expected, no separate technical-only model.
"""
import json
from datetime import datetime, timedelta, timezone

from app.ml.config import load_ml_config
from app.ml.features.builder import build_features
from app.tracking.labels import DEAD_BAND_PCT, HORIZON_BARS, derive_direction

STRIDE_24H_BARS = 7   # ~one session of 1h bars; keeps consecutive 24h windows roughly non-overlapping


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def _all_snaps(con, stock_id: int, interval: str) -> list[tuple[str, dict]]:
    """All (timestamp, indicators) for (stock, interval), oldest -> newest."""
    cur = await con.execute(
        "SELECT timestamp, indicators_json FROM technical_snapshots "
        "WHERE stock_id=? AND bar_interval=? ORDER BY timestamp ASC", (stock_id, interval))
    return [(r["timestamp"], json.loads(r["indicators_json"])) for r in await cur.fetchall()]


def _first_at_or_after(snaps, entry_ts: str, hours: int, start: int) -> int | None:
    target = _parse(entry_ts) + timedelta(hours=hours)
    for k in range(start, len(snaps)):
        if _parse(snaps[k][0]) >= target:
            return k
    return None


async def _make_sample(con, redis, ref, tf, snaps, i, j, band) -> dict | None:
    entry_ts, entry_ind = snaps[i]
    exit_ts, exit_ind = snaps[j]
    entry_close, exit_close = entry_ind.get("close"), exit_ind.get("close")
    if not entry_close or exit_close is None:
        return None
    move_pct = (exit_close - entry_close) / entry_close * 100.0
    vector, meta = await build_features(con, redis, ref, tf, entry_ts)
    return {
        "stock_id": ref.id, "entry_ts": entry_ts, "exit_ts": exit_ts,
        "entry_close": entry_close, "exit_close": exit_close, "move_pct": move_pct,
        "label": derive_direction(move_pct, band), "features": vector, "meta": meta,
    }


async def build_dataset(con, redis, stock_refs, timeframe: str) -> list[dict]:
    """Returns samples (chronological by entry_ts) across all stock_refs for one timeframe."""
    interval = load_ml_config()["bar_interval"][timeframe]
    band = DEAD_BAND_PCT[timeframe]
    samples: list[dict] = []
    for ref in stock_refs:
        snaps = await _all_snaps(con, ref.id, interval)
        n = len(snaps)
        if timeframe == "24h":                                   # wall-clock window
            i = 0
            while i < n:
                j = _first_at_or_after(snaps, snaps[i][0], 24, i + 1)
                if j is None:
                    break
                s = await _make_sample(con, redis, ref, timeframe, snaps, i, j, band)
                if s:
                    samples.append(s)
                i += STRIDE_24H_BARS
        else:                                                    # bar-count window, stride = horizon
            h = HORIZON_BARS[timeframe]
            for i in range(0, n - h, h):
                s = await _make_sample(con, redis, ref, timeframe, snaps, i, i + h, band)
                if s:
                    samples.append(s)
    samples.sort(key=lambda s: s["entry_ts"])
    return samples
