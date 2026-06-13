import csv
import sqlite3
import sys
from pathlib import Path

from app.config import get_settings

COLUMNS = ["symbol", "exchange", "region", "company_name", "company_name_ko",
           "company_group", "security_type", "currency", "board", "yfinance_ticker",
           "finnhub_ticker", "adr_ratio", "xmkt_reference", "listing_price_usd"]


def seed_stocks(db_path: str, csv_path: str) -> int:
    """Insert the stock universe, but only if `stocks` is empty. Returns rows inserted."""
    con = sqlite3.connect(db_path)
    try:
        if con.execute("SELECT COUNT(*) FROM stocks").fetchone()[0] > 0:
            return 0
        inserted = 0
        placeholders = ",".join("?" * len(COLUMNS))
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                values = [(row[c] if row[c] != "" else None) for c in COLUMNS]
                con.execute(
                    f"INSERT INTO stocks ({','.join(COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
                inserted += 1
        con.commit()
        return inserted
    finally:
        con.close()


def _default_csv_path() -> str:
    # backend/app/db/seed.py -> <repo or /srv>/config/seed_stocks.csv  (cwd-independent;
    # works locally and in the container, where config is copied beside backend/).
    return str(Path(__file__).resolve().parents[3] / "config" / "seed_stocks.csv")


if __name__ == "__main__":
    settings = get_settings()
    n = seed_stocks(settings.sqlite_path, _default_csv_path())
    print(f"seeded {n} stocks" if n else "stocks already seeded")
    sys.exit(0)
