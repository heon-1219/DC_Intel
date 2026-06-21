"""M10c — db_backup (deployment-architecture §2.3)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db.migrate import migrate
from app.jobs.db_backup import retained, run_db_backup

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


def test_retained_keeps_14_daily_plus_weekly():
    today = date(2026, 6, 21)
    dates = [today - timedelta(days=i) for i in range(120)]  # 120 consecutive days
    keep = retained(dates, today)
    # the 14 most recent dailies are all kept
    for i in range(14):
        assert (today - timedelta(days=i)) in keep
    # a 100-day-old snapshot is well beyond 14 daily + 8 weekly → pruned
    assert (today - timedelta(days=100)) not in keep
    # bounded: at most 14 + 8 distinct kept
    assert len(keep) <= 22


@pytest.mark.asyncio
async def test_run_db_backup_creates_snapshot_and_prunes(tmp_path):
    db = str(tmp_path / "app.db")
    migrate(db, MIG)
    backup_dir = str(tmp_path / "backups")
    Path(backup_dir).mkdir()
    now = datetime(2026, 6, 21, 19, 30, tzinfo=timezone.utc)
    # 14 recent daily dummies (so retention's 14-daily floor is already full) + one ancient snapshot.
    for i in range(1, 15):
        d = (now.date() - timedelta(days=i)).strftime("%Y%m%d")
        (Path(backup_dir) / f"dcintel-{d}.db").write_text("dummy")
    old = Path(backup_dir) / "dcintel-20260101.db"
    old.write_text("stale")

    snap = await run_db_backup(db, backup_dir, now=now)

    assert Path(snap).name == "dcintel-20260621.db" and Path(snap).exists()
    assert Path(snap).stat().st_size > 0  # real sqlite snapshot, not empty
    assert not old.exists()  # 2026-01-01 is >14 daily + >8 weeks old → pruned
