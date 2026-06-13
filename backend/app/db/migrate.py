import sqlite3
import sys
from pathlib import Path

from app.config import get_settings


def migrate(db_path: str, migrations_dir: str) -> list[str]:
    """Apply pending numbered .sql migrations in one transaction each.

    Returns the filenames newly applied (empty if already up to date).
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, filename TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )
    con.commit()
    applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
    newly: list[str] = []
    for f in sorted(Path(migrations_dir).glob("*.sql")):
        version = f.name.split("_", 1)[0]
        if version in applied:
            continue
        sql = f.read_text(encoding="utf-8")
        # Wrap the whole file in one transaction so a mid-file failure rolls it all back.
        con.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        con.execute("INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                    (version, f.name))
        con.commit()
        newly.append(f.name)
    con.close()
    return newly


def _default_migrations_dir() -> str:
    # backend/app/db/migrate.py -> backend/migrations  (cwd-independent)
    return str(Path(__file__).resolve().parents[2] / "migrations")


if __name__ == "__main__":
    settings = get_settings()
    done = migrate(settings.sqlite_path, _default_migrations_dir())
    print(f"applied: {done}" if done else "schema up to date")
    sys.exit(0)
