"""win_rate_monitor (deployment-architecture §8.3): daily 07:30 KST. For each of the 6 timeframes,
the rolling 7-day DIRECTIONAL win rate from prediction_outcomes (deduped like accuracy_stats). With
≥ WIN_RATE_MIN_SAMPLE graded directional predictions: < WIN_RATE_ALERT_THRESHOLD → ERROR alert;
else < WIN_RATE_WARN_THRESHOLD (the 52% ship gate) → WARN. The product's honesty promise depends on
catching a degraded model early."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.core.alerts import emit_alert
from app.db.connection import connect
from app.ml.config import TIMEFRAMES


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def run_win_rate_monitor(db: str, *, now: datetime | None = None) -> list[dict]:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    cutoff = _iso(now - timedelta(days=7))

    async with connect(db) as con:
        cur = await con.execute(
            "SELECT p.timeframe, p.direction, p.model_version, MAX(o.marked_correct) AS correct "
            "FROM predictions p JOIN prediction_outcomes o ON o.prediction_id = p.id "
            "WHERE p.created_at >= ? GROUP BY p.timeframe, p.direction, p.window_closes_at",
            (cutoff,))
        rows = [dict(r) for r in await cur.fetchall()]

    by_tf: dict[str, list[dict]] = {}
    for r in rows:
        by_tf.setdefault(r["timeframe"], []).append(r)

    alerts: list[dict] = []
    for tf in TIMEFRAMES:
        dirs = [r for r in by_tf.get(tf, []) if r["direction"] in ("up", "down")]
        n = len(dirs)
        if n < s.win_rate_min_sample:
            continue
        wins = sum(r["correct"] for r in dirs)
        wr = wins / n
        mv = Counter(r["model_version"] for r in dirs).most_common(1)[0][0]
        msg = f"{tf}: 7-day win rate {wr:.2f} over {n} predictions (model {mv})"
        if wr < s.win_rate_alert_threshold:
            alerts.append(emit_alert("ERROR", "win_rate.degraded", msg,
                                     timeframe=tf, win_rate=round(wr, 4), n=n, model_version=mv))
        elif wr < s.win_rate_warn_threshold:
            alerts.append(emit_alert("WARN", "win_rate.below_gate", msg,
                                     timeframe=tf, win_rate=round(wr, 4), n=n, model_version=mv))
    return alerts
