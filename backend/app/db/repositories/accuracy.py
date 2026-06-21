"""Public win-rate aggregation (win-loss-tracking.md §6). De-duplicates the cache-hit audit
duplicates (multiple users predicting the same stock/tf/window) via GROUP BY (timeframe, direction,
window_closes_at) + MAX(marked_correct), so a popular stock isn't double-counted. A realized neutral
is a LOSS for a directional call (in directional.predictions, not wins). Window filters by
predictions.created_at (when the call was MADE). low_sample / null win-rate guard small samples."""
from datetime import datetime, timedelta, timezone

from app.ml.config import TIMEFRAMES

MIN_SAMPLE = 20


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    correct = sum(r["correct"] for r in rows)
    dirs = [r for r in rows if r["direction"] in ("up", "down")]
    dpred = len(dirs)
    dwins = sum(r["correct"] for r in dirs)
    return {
        "graded": n,
        "exact_accuracy_pct": round(100 * correct / n, 1) if n else None,
        "directional": {"predictions": dpred, "wins": dwins, "losses": dpred - dwins,
                        "win_rate_pct": round(100 * dwins / dpred, 1) if dpred else None},
    }


async def accuracy_stats(con, stock_id: int, *, window: str = "all", now_iso: str,
                         include_model_versions: bool = False, timeframe: str | None = None) -> dict:
    cutoff = None
    if window in ("30d", "90d"):
        cutoff = _iso(_parse(now_iso) - timedelta(days=30 if window == "30d" else 90))
    df = " AND p.created_at >= ?" if cutoff else ""
    tff = " AND p.timeframe = ?" if timeframe else ""
    extra = ([cutoff] if cutoff else []) + ([timeframe] if timeframe else [])
    params = [stock_id] + extra

    cur = await con.execute(
        "SELECT p.timeframe, p.direction, p.model_version, MAX(o.marked_correct) AS correct "
        "FROM predictions p JOIN prediction_outcomes o ON o.prediction_id = p.id "
        f"WHERE p.stock_id = ?{df}{tff} GROUP BY p.timeframe, p.direction, p.window_closes_at",
        params)
    rows = [dict(r) for r in await cur.fetchall()]

    pcur = await con.execute(
        f"SELECT COUNT(*) AS c FROM predictions p WHERE p.stock_id = ? AND p.checked_at IS NULL"
        f"{df}{tff}", params)
    pending = (await pcur.fetchone())["c"]

    overall = _agg(rows)
    by_tf = []
    for tf in TIMEFRAMES:
        tfr = [r for r in rows if r["timeframe"] == tf]
        if not tfr:
            continue
        a = _agg(tfr)
        win_rate = a["directional"]["win_rate_pct"] if a["graded"] >= MIN_SAMPLE else None
        by_tf.append({"timeframe": tf, "graded": a["graded"],
                      "exact_accuracy_pct": a["exact_accuracy_pct"],
                      "directional": {"predictions": a["directional"]["predictions"],
                                      "wins": a["directional"]["wins"], "win_rate_pct": win_rate}})

    out = {
        "graded_total": overall["graded"], "pending": pending,
        "exact_accuracy_pct": overall["exact_accuracy_pct"], "directional": overall["directional"],
        "neutral_predictions": sum(1 for r in rows if r["direction"] == "neutral"),
        "low_sample": overall["graded"] < MIN_SAMPLE, "by_timeframe": by_tf,
    }
    if include_model_versions:
        mvs: dict = {}
        for r in rows:
            mvs.setdefault(r["model_version"], []).append(r)
        out["by_model_version"] = [{"model_version": mv, **_agg(rs)} for mv, rs in sorted(mvs.items())]
    return out
