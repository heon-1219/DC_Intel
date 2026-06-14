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


@pytest.mark.asyncio
async def test_get_stock_includes_names(db):
    async with connect(db) as con:
        ref = await repo.get_stock(con, "005930", "KRX")
    assert ref.company_name == "Samsung Electronics" and ref.company_name_ko == "삼성전자"


@pytest.mark.asyncio
async def test_company_listings_single_then_grouped(db):
    async with connect(db) as con:
        res = await repo.get_company_listings(con, "005930", "KRX")
        assert res is not None
        names, listings = res
        assert names["en"] == "Samsung Electronics"
        assert [lst.instrument for lst in listings] == ["005930:KRX"]

        # Add a grouped ADR listing, then expect both back.
        await con.execute(
            "INSERT INTO stocks (symbol,exchange,region,company_name,company_group,"
            "security_type,currency,adr_ratio,yfinance_ticker) "
            "VALUES ('SSNLF','OTC','US','Samsung Electronics','samsung-electronics',"
            "'adr','USD',0.5,'SSNLF')"
        )
        await con.commit()
        _, listings2 = await repo.get_company_listings(con, "005930", "KRX")
        by_ex = {lst.exchange: lst for lst in listings2}
        assert sorted(by_ex) == ["KRX", "OTC"]
        assert by_ex["OTC"].adr_ratio == 0.5 and by_ex["OTC"].currency == "USD"


@pytest.mark.asyncio
async def test_company_listings_unknown_returns_none(db):
    async with connect(db) as con:
        assert await repo.get_company_listings(con, "ZZZZ", "KRX") is None
