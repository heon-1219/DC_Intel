import sqlite3
from pathlib import Path

from app.db.migrate import migrate
from app.db.seed import seed_stocks

MIG_DIR = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


def _count(db):
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
    con.close()
    return n


def test_seed_populates_when_empty(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    inserted = seed_stocks(db, CSV)
    assert inserted >= 12
    assert _count(db) == inserted


def test_seed_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    seed_stocks(db, CSV)
    again = seed_stocks(db, CSV)  # table non-empty -> no-op
    assert again == 0


def test_seed_resolves_symbol_exchange(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    seed_stocks(db, CSV)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT yfinance_ticker FROM stocks WHERE symbol='005930' AND exchange='KRX'"
    ).fetchone()
    con.close()
    assert row[0] == "005930.KS"


def test_seed_nulls_empty_csv_fields(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG_DIR)
    seed_stocks(db, CSV)
    con = sqlite3.connect(db)
    # KRX rows have no finnhub_ticker in the CSV -> should be NULL, not "".
    finnhub = con.execute(
        "SELECT finnhub_ticker FROM stocks WHERE symbol='005930' AND exchange='KRX'"
    ).fetchone()[0]
    # PKX ADR has an adr_ratio of 1.
    adr = con.execute(
        "SELECT adr_ratio FROM stocks WHERE symbol='PKX' AND exchange='NYSE'"
    ).fetchone()[0]
    con.close()
    assert finnhub is None
    assert adr == 1  # REAL column affinity coerces the CSV "1" to 1.0
