"""db_backup (deployment-architecture §2.3): daily 04:30 KST. `VACUUM INTO` an online-safe snapshot
(never cp a live WAL database) into the local BACKUP_DIR. Retention: 14 daily + 8 weekly. Local-first
v1 keeps snapshots on the local volume ($0); a cloud upload (BACKUP_BUCKET) is an optional later add.
Any failure → ERROR alert."""
import asyncio
import os
import re
import sqlite3
from datetime import date, datetime, timezone

from app.core.alerts import emit_alert

_NAME_RE = re.compile(r"^dcintel-(\d{8})\.db$")


def retained(dates: list[date], today: date) -> set[date]:
    """Keep the 14 most recent daily snapshots + the newest snapshot per ISO week for any week within
    the last 8 weeks (~56 days). Snapshots older than that are pruned."""
    desc = sorted(set(dates), reverse=True)
    keep = set(desc[:14])
    per_week: dict[tuple[int, int], date] = {}
    for d in desc:  # desc → first seen per week is the newest in that week
        per_week.setdefault(d.isocalendar()[:2], d)
    for d in per_week.values():
        if (today - d).days <= 56:  # within the last ~8 weeks
            keep.add(d)
    return keep


def _vacuum_into(db: str, snap: str) -> None:
    con = sqlite3.connect(db)
    try:
        con.execute("VACUUM INTO '%s'" % snap.replace("'", "''"))
    finally:
        con.close()


def _prune(backup_dir: str, today: date) -> None:
    files: dict[date, str] = {}
    for name in os.listdir(backup_dir):
        m = _NAME_RE.match(name)
        if not m:
            continue
        try:
            files[datetime.strptime(m.group(1), "%Y%m%d").date()] = os.path.join(backup_dir, name)
        except ValueError:
            continue
    keep = retained(list(files), today)
    for d, path in files.items():
        if d not in keep:
            try:
                os.remove(path)
            except OSError:
                pass


async def run_db_backup(db: str, backup_dir: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    os.makedirs(backup_dir, exist_ok=True)
    snap = os.path.join(backup_dir, f"dcintel-{now.strftime('%Y%m%d')}.db")
    try:
        await asyncio.to_thread(_vacuum_into, db, snap)
    except Exception as e:  # noqa: BLE001
        emit_alert("ERROR", "backup.failed", f"DB backup failed: {e}", path=snap)
        raise
    _prune(backup_dir, now.date())
    return snap
