"""M10g — response-time metrics accumulator + hourly rollup (deployment-architecture §8.2/§10)."""
import json

import pytest

from app.core import metrics


@pytest.fixture(autouse=True)
def _reset():
    metrics.rollup_and_reset()
    yield
    metrics.rollup_and_reset()


def test_record_and_rollup_then_reset():
    metrics.record(10.0, 200)
    metrics.record(30.0, 200)
    metrics.record(5.0, 404)
    m = metrics.rollup_and_reset()
    assert m["count"] == 3 and m["ok"] == 2 and m["client_err"] == 1
    assert m["avg_ms"] == 15.0 and m["max_ms"] == 30.0
    assert metrics.rollup_and_reset()["count"] == 0  # cleared


@pytest.mark.asyncio
async def test_rollup_warns_on_high_429_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("ALERT_LOG_PATH", str(tmp_path / "a.log"))
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "")
    from app.config import get_settings
    get_settings.cache_clear()
    for _ in range(99):
        metrics.record(5.0, 200)
    metrics.record(5.0, 429)
    metrics.record(5.0, 429)  # 2/101 ≈ 2% > 1%, count ≥ 100

    from app.jobs.metrics_rollup import run_metrics_rollup
    m = await run_metrics_rollup()
    assert m["count"] == 101 and m["rate_limited"] == 2
    lines = (tmp_path / "a.log").read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(ln)["event"] == "rate_limit.high" for ln in lines)
    get_settings.cache_clear()
