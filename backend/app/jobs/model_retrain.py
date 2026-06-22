"""model_retrain (deployment-architecture §3.1, prediction-model §7.7): weekly walk-forward retrain
+ promotion guard. For each timeframe, retrain on the latest backfilled history and write the
artifact. The serving loader only promotes a GATE-PASSED latest artifact, so a failed or gate-missing
retrain never demotes the running model — production keeps the old artifact. Exceptions → ERROR alert."""
from datetime import datetime, timezone

from app.core import logging as applog
from app.core.alerts import emit_alert
from app.ml.config import TIMEFRAMES
from app.ml.train import train_and_write


async def run_model_retrain(db: str, models_root: str, *, timeframes=TIMEFRAMES,
                            now: datetime | None = None, git_commit: str = "scheduled") -> list[dict]:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")
    log = applog.get_logger()
    results: list[dict] = []
    for tf in timeframes:
        try:
            res = await train_and_write(db, tf, models_root, now_iso=now_iso, git_commit=git_commit)
        except Exception as e:  # noqa: BLE001 - a retrain failure must not crash the scheduler
            emit_alert("ERROR", "model_retrain.failed", f"retrain failed for {tf}: {e}", timeframe=tf)
            results.append({"timeframe": tf, "status": "error"})
            continue
        if res is None:
            log.info("model_retrain.skipped", timeframe=tf, reason="insufficient_samples")
            results.append({"timeframe": tf, "status": "insufficient"})
        else:
            log.info("model_retrain.done", timeframe=tf, model_version=res["model_version"],
                     gate_passed=res["passed"], win_rate=res["win_rate"])
            results.append({"timeframe": tf, "status": "trained", "passed": res["passed"],
                            "model_version": res["model_version"]})
    return results
