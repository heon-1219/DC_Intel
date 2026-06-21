"""M10b — win_rate_monitor (deployment-architecture §8.3)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("ALERT_LOG_PATH", str(tmp_path / "alerts.log"))
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "")
    monkeypatch.setenv("WIN_RATE_MIN_SAMPLE", "4")  # keep the fixture small
    from app.config import get_settings
    get_settings.cache_clear()
    db = get_settings().sqlite_path
    migrate(db, MIG)
    seed_stocks(db, CSV)
    yield tmp_path, db
    get_settings.cache_clear()


async def _seed(db, tf, n, wins):
    async with connect(db) as con:
        await con.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, preferred_language) "
            "VALUES (1, 't@x.com', 'h', 'en')")
        await con.commit()
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        for i in range(n):
            pid = await prepo.insert_prediction(
                con, user_id=1, stock_id=ref.id, timeframe=tf, direction="up", confidence=60,
                reasoning_json={}, model_version="5d-lr-20260620.1",
                window_closes_at=f"2026-06-{10 + i:02d}T00:00:00Z")
            await prepo.record_outcome(
                con, prediction_id=pid, actual_direction="up", actual_price_change_percent=1.0,
                marked_correct=1 if i < wins else 0, exit_price=1.0, high_impact_event_overlap=0,
                checked_at_iso="2026-06-20T00:00:00Z")


@pytest.mark.asyncio
async def test_alerts_on_degraded_and_below_gate(env):
    tmp_path, db = env
    from app.jobs.win_rate_monitor import run_win_rate_monitor
    await _seed(db, "5d", 4, 1)   # 0.25 → ERROR (< 0.50)
    await _seed(db, "24h", 4, 2)  # 0.50 → WARN  (< 0.52, not < 0.50)
    await _seed(db, "2d", 4, 3)   # 0.75 → no alert
    await _seed(db, "1h", 3, 0)   # below min_sample → skipped

    alerts = await run_win_rate_monitor(db, now=datetime.now(timezone.utc))
    by_event = {a["event"]: a for a in alerts}
    assert by_event["win_rate.degraded"]["timeframe"] == "5d"
    assert by_event["win_rate.below_gate"]["timeframe"] == "24h"
    assert len(alerts) == 2  # 2d ok, 1h under-sampled

    lines = (tmp_path / "alerts.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert {json.loads(ln)["level"] for ln in lines} == {"ERROR", "WARN"}
