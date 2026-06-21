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


_SEARCH_COLS = ("symbol, exchange, region, currency, board, security_type, adr_ratio, "
                "company_group, company_name, company_name_ko")


def _group_key(row) -> str:
    return row["company_group"] or f"{row['symbol']}:{row['exchange']}"


async def search_listings(con, q: str, *, limit: int) -> list[dict]:
    """Company-grouped search (backend-design §6.3): symbol PREFIX + company_name/_ko SUBSTRING
    (case-insensitive), excluding index rows. Returns up to `limit` company groups in match order,
    each carrying ALL its active listings with is_primary + kind derived (NO prices — the /search
    handler merges the live px:quote/px:fx overlay per request)."""
    # Escape LIKE meta-characters so a literal % or _ in the query is matched literally, not as a
    # wildcard (else q='%' would match the whole universe). Escape backslash FIRST.
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    prefix, sub = esc + "%", "%" + esc + "%"
    cur = await con.execute(
        f"SELECT {_SEARCH_COLS} FROM stocks WHERE is_active = 1 AND security_type != 'index' "
        "AND (LOWER(symbol) LIKE ? ESCAPE '\\' OR LOWER(company_name) LIKE ? ESCAPE '\\' "
        "OR LOWER(company_name_ko) LIKE ? ESCAPE '\\') ORDER BY symbol",
        (prefix, sub, sub),
    )
    order, seen = [], set()
    for r in await cur.fetchall():
        k = _group_key(r)
        if k not in seen:
            seen.add(k)
            order.append(k)
        if len(order) >= limit:
            break
    if not order:
        return []
    # Pull ALL active listings, keep those in a matched group (a group's non-matching listings —
    # e.g. an ADR when you searched the common's Korean name — still belong in the company row).
    cur = await con.execute(
        f"SELECT {_SEARCH_COLS} FROM stocks WHERE is_active = 1 AND security_type != 'index'")
    by_group: dict[str, list] = {}
    for r in await cur.fetchall():
        k = _group_key(r)
        if k in seen:
            by_group.setdefault(k, []).append(r)

    out = []
    for k in order:
        # primary = the non-ADR (adr_ratio NULL) home listing first; tie-break by symbol.
        rows = sorted(by_group[k], key=lambda r: (r["adr_ratio"] is not None, r["symbol"]))
        primary = rows[0]
        out.append({
            "company_name_en": primary["company_name"],
            "company_name_ko": primary["company_name_ko"],
            "listings": [{
                "instrument": f"{r['symbol']}:{r['exchange']}", "symbol": r["symbol"],
                "exchange": r["exchange"], "board": r["board"], "currency": r["currency"],
                "adr_ratio": r["adr_ratio"],
                "is_primary": (r["symbol"], r["exchange"]) == (primary["symbol"], primary["exchange"]),
                "kind": "adr" if r["adr_ratio"] else "common",
            } for r in rows],
        })
    return out


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
