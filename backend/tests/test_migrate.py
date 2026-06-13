import sqlite3
from pathlib import Path

import pytest

from app.db.migrate import migrate

# Resolve the migrations dir relative to this test file, not the cwd.
MIG_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _tables(db):
    con = sqlite3.connect(db)
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    return {r[0] for r in rows}


def test_migrate_creates_all_tables(tmp_path):
    db = str(tmp_path / "t.db")
    applied = migrate(db, MIG_DIR)
    assert "001_initial_schema.sql" in applied
    expected = {"users", "stocks", "predictions", "prediction_outcomes", "sentiment_logs",
                "economic_events", "technical_snapshots", "feature_importance_logs",
                "market_intel", "schema_migrations"}
    assert expected.issubset(_tables(db))


def test_migrate_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    second = migrate(db, MIG_DIR)
    assert second == []


def test_check_constraint_rejects_bad_timeframe(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO stocks (symbol,exchange,region,company_name,yfinance_ticker) "
                "VALUES ('T','NASDAQ','US','T','T')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO predictions (stock_id,timeframe,direction,confidence,"
                    "reasoning_json,model_version,window_closes_at) "
                    "VALUES (1,'9h','up',50,'{}','24h-xgb-20260608.1','2026-01-01T00:00:00Z')")
    con.close()
