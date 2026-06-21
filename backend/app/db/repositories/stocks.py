from dataclasses import dataclass

from app.providers.base import StockRef

_COLS = ("id, symbol, exchange, region, currency, yfinance_ticker, finnhub_ticker, "
         "company_name, company_name_ko, xmkt_reference")


@dataclass(frozen=True)
class Listing:
    instrument: str
    symbol: str
    exchange: str
    currency: str
    adr_ratio: float | None


def _row_to_ref(row) -> StockRef:
    return StockRef(
        id=row["id"], symbol=row["symbol"], exchange=row["exchange"], region=row["region"],
        currency=row["currency"], yfinance_ticker=row["yfinance_ticker"],
        finnhub_ticker=row["finnhub_ticker"], company_name=row["company_name"],
        company_name_ko=row["company_name_ko"], xmkt_reference=row["xmkt_reference"],
    )


async def get_stock(con, symbol: str, exchange: str) -> StockRef | None:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE symbol = ? AND exchange = ? AND is_active = 1",
        (symbol, exchange),
    )
    row = await cur.fetchone()
    return _row_to_ref(row) if row else None


async def get_by_id(con, stock_id: int) -> StockRef | None:
    cur = await con.execute(f"SELECT {_COLS} FROM stocks WHERE id = ?", (stock_id,))
    row = await cur.fetchone()
    return _row_to_ref(row) if row else None


async def list_active_by_region(con, region: str) -> list[StockRef]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE region = ? AND is_active = 1 "
        "AND security_type != 'index'",
        (region,),
    )
    return [_row_to_ref(r) for r in await cur.fetchall()]


async def list_active_indexes(con) -> list[StockRef]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE is_active = 1 AND security_type = 'index'"
    )
    return [_row_to_ref(r) for r in await cur.fetchall()]


async def list_active_all(con) -> list[StockRef]:
    """Every active stock incl. index pseudo-rows — the indicator job's scope."""
    cur = await con.execute(f"SELECT {_COLS} FROM stocks WHERE is_active = 1")
    return [_row_to_ref(r) for r in await cur.fetchall()]


async def get_company_listings(con, symbol: str, exchange: str):
    """For the company owning {symbol}:{exchange}, return (names, [Listing]) across all its
    listings (those sharing company_group, else just the one). None if the base is unknown."""
    cur = await con.execute(
        "SELECT company_group, company_name, company_name_ko FROM stocks "
        "WHERE symbol = ? AND exchange = ? AND is_active = 1",
        (symbol, exchange),
    )
    base = await cur.fetchone()
    if base is None:
        return None
    names = {"en": base["company_name"], "ko": base["company_name_ko"]}
    group = base["company_group"]
    if group:
        cur = await con.execute(
            "SELECT symbol, exchange, currency, adr_ratio FROM stocks "
            "WHERE company_group = ? AND is_active = 1 ORDER BY symbol",
            (group,),
        )
    else:
        cur = await con.execute(
            "SELECT symbol, exchange, currency, adr_ratio FROM stocks "
            "WHERE symbol = ? AND exchange = ? AND is_active = 1",
            (symbol, exchange),
        )
    listings = [
        Listing(instrument=f"{r['symbol']}:{r['exchange']}", symbol=r["symbol"],
                exchange=r["exchange"], currency=r["currency"], adr_ratio=r["adr_ratio"])
        for r in await cur.fetchall()
    ]
    return names, listings
