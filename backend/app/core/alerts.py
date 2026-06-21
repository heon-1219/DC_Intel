"""Local-first alert channel (deployment-architecture §8.3). Each alert is ONE JSON line appended to
ALERT_LOG_PATH plus a structlog console line at the right level. If ALERT_WEBHOOK_URL is set the same
alert is also POSTed best-effort. Alerting must NEVER crash the caller (a failed alert is swallowed)."""
import json
import os
from datetime import datetime, timezone

from app.config import get_settings
from app.core import logging as applog

_LOG_METHOD = {"ERROR": "error", "WARN": "warning", "WARNING": "warning", "INFO": "info"}


def emit_alert(level: str, event: str, message: str, **fields) -> dict:
    """Record an alert (level ∈ ERROR|WARN|INFO). Returns the structured record (also for tests)."""
    s = get_settings()
    lvl = level.upper()
    record = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": lvl,
        "event": event,
        "message": message,
        **fields,
    }
    try:
        path = s.alert_log_path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - alerting never crashes the caller
        pass

    log = applog.get_logger()
    getattr(log, _LOG_METHOD.get(lvl, "warning"))(f"alert.{event}", message=message, **fields)

    if s.alert_webhook_url:
        _post_webhook(s.alert_webhook_url, record)
    return record


def _post_webhook(url: str, record: dict) -> None:
    try:
        import urllib.request

        req = urllib.request.Request(
            url, data=json.dumps(record).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 - operator-provided URL
    except Exception:  # noqa: BLE001 - best-effort
        pass
