from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as repo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    migrate(p, MIG)
    seed_stocks(p, CSV)
    return p


@pytest.mark.asyncio
async def test_get_stock_found_and_missing(db):
    async with connect(db) as con:
        ref = await repo.get_stock(con, "005930", "KRX")
        assert ref is not None
        assert ref.yfinance_ticker == "005930.KS" and ref.region == "KR" and ref.currency == "KRW"
        assert await repo.get_stock(con, "ZZZZ", "KRX") is None


@pytest.mark.asyncio
async def test_list_active_by_region_excludes_indexes(db):
    async with connect(db) as con:
        kr = await repo.list_active_by_region(con, "KR")
    symbols = {r.symbol for r in kr}
    assert "005930" in symbols
    assert "KOSPI" not in symbols  # index pseudo-rows excluded from polling
