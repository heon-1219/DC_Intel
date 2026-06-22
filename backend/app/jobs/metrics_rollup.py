"""metrics_rollup (deployment-architecture §8.2/§10): hourly. Roll up the in-process response-time +
status accumulator into an INFO log line; a sustained 429 rate > 1% with enough traffic → WARN (§10:
'either an abuser or limits set too tight')."""
from app.core import logging as applog
from app.core import metrics
from app.core.alerts import emit_alert

_MIN_FOR_429_ALERT = 100


async def run_metrics_rollup() -> dict:
    m = metrics.rollup_and_reset()
    applog.get_logger().info("metrics.rollup", **m)
    if m["count"] >= _MIN_FOR_429_ALERT and m["rate_429"] > 0.01:
        emit_alert("WARN", "rate_limit.high",
                   f"429 rate {m['rate_429']:.2%} over {m['count']} requests", **m)
    return m
