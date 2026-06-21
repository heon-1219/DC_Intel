"""M10a — local-first alert channel (deployment-architecture §8.3)."""
import json

import pytest


@pytest.fixture
def alert_log(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("ALERT_LOG_PATH", str(tmp_path / "logs" / "alerts.log"))
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "")
    from app.config import get_settings
    get_settings.cache_clear()
    yield tmp_path / "logs" / "alerts.log"
    get_settings.cache_clear()


def test_emit_alert_writes_one_json_line(alert_log):
    from app.core.alerts import emit_alert
    rec = emit_alert("ERROR", "win_rate.degraded", "5d rolling win rate 0.41",
                     timeframe="5d", win_rate=0.41, model_version="5d-lr-20260620.1")
    assert rec["level"] == "ERROR"
    lines = alert_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["level"] == "ERROR" and obj["event"] == "win_rate.degraded"
    assert obj["timeframe"] == "5d" and obj["win_rate"] == 0.41 and "ts" in obj


def test_alerts_append(alert_log):
    from app.core.alerts import emit_alert
    emit_alert("WARN", "a", "first")
    emit_alert("INFO", "b", "second")
    lines = alert_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["event"] == "b"
