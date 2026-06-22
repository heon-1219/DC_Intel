"""M10g — model_retrain orchestration + promotion guard (deployment-architecture §3.1)."""
import json

import pytest

from app.jobs import model_retrain


@pytest.mark.asyncio
async def test_retrain_orchestrates_and_alerts(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("ALERT_LOG_PATH", str(tmp_path / "a.log"))
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "")
    from app.config import get_settings
    get_settings.cache_clear()

    async def fake_train(db, tf, root, *, now_iso, git_commit="scheduled"):
        if tf == "5d":
            return {"timeframe": tf, "model_version": "5d-lr-x", "algorithm": "logistic",
                    "win_rate": 0.53, "coverage": 1.0, "passed": True, "n_samples": 900, "path": "/x"}
        if tf == "1h":
            raise RuntimeError("boom")
        return None  # insufficient samples

    monkeypatch.setattr(model_retrain, "train_and_write", fake_train)
    res = await model_retrain.run_model_retrain("db.sqlite", str(tmp_path),
                                                timeframes=["5d", "1h", "5h"])
    by_tf = {r["timeframe"]: r for r in res}
    assert by_tf["5d"]["status"] == "trained" and by_tf["5d"]["passed"] is True
    assert by_tf["1h"]["status"] == "error"          # exception → ERROR alert, old model kept
    assert by_tf["5h"]["status"] == "insufficient"

    lines = (tmp_path / "a.log").read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(ln)["event"] == "model_retrain.failed" for ln in lines)
    get_settings.cache_clear()
