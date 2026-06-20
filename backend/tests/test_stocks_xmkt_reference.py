"""M5d: stocks repo exposes xmkt_reference (the cross-market reference metadata) on StockRef."""
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


@pytest.mark.asyncio
async def test_stockref_carries_xmkt_reference(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    async with connect(db) as con:
        samsung = await srepo.get_stock(con, "005930", "KRX")
        apple = await srepo.get_stock(con, "AAPL", "NASDAQ")
        hyundai = await srepo.get_stock(con, "005380", "KRX")
    assert samsung.xmkt_reference == "SOXX"     # from the seed CSV
    assert apple.xmkt_reference == "^N225"
    assert hyundai.xmkt_reference is None        # empty in seed -> None (resolver falls back to SPY)
