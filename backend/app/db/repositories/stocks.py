from app.providers.base import StockRef

_COLS = "id, symbol, exchange, region, currency, yfinance_ticker, finnhub_ticker"


def _row_to_ref(row) -> StockRef:
    return StockRef(
        id=row["id"], symbol=row["symbol"], exchange=row["exchange"], region=row["region"],
        currency=row["currency"], yfinance_ticker=row["yfinance_ticker"],
        finnhub_ticker=row["finnhub_ticker"],
    )


async def get_stock(con, symbol: str, exchange: str) -> StockRef | None:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE symbol = ? AND exchange = ? AND is_active = 1",
        (symbol, exchange),
    )
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
