"""M6i: per-event 'affects your stocks' matching for a logged-in user (economic-calendar §9).
Precedence (strongest wins): stock (held stock named in the event) > sector (held stock is a member
of an affected sector) > market (the event hits the held stock's market index). Pure + testable."""
from app.calendar.registry import sector_codes_for

# A stock's market index code (matches the index codes used in the event registry).
_MARKET_INDEX = {"KRX": "KOSPI", "NASDAQ": "NASDAQ_COMPOSITE", "NYSE": "SP500", "AMEX": "SP500"}


def _codes(items) -> set:
    return {(i["code"] if isinstance(i, dict) else i) for i in (items or [])}


def compute_event_affects(holdings, affected, sectors) -> dict:
    """holdings: list of (symbol, exchange) the user holds (recent predictions). affected: the parsed
    affected_stocks_json (or None). sectors: the loaded sectors map. Returns the per-event overlay."""
    none = {"affects_your_stocks": False, "match_level": None, "matched_symbols": []}
    if not affected:
        return none
    aff_stocks = {f"{s['symbol']}:{s['exchange']}" for s in (affected.get("stocks") or [])}
    aff_sectors = _codes(affected.get("sectors"))
    aff_indexes = _codes(affected.get("indexes"))

    stock_hits, has_sector, has_market = [], False, False
    for sym, exch in holdings:
        inst = f"{sym}:{exch}"
        if inst in aff_stocks:
            stock_hits.append(inst)
        elif set(sector_codes_for(sectors, sym, exch)) & aff_sectors:
            has_sector = True
        elif _MARKET_INDEX.get(exch) in aff_indexes:
            has_market = True

    if stock_hits:
        return {"affects_your_stocks": True, "match_level": "stock",
                "matched_symbols": sorted(set(stock_hits))}
    if has_sector:
        return {"affects_your_stocks": True, "match_level": "sector", "matched_symbols": []}
    if has_market:
        return {"affects_your_stocks": True, "match_level": "market", "matched_symbols": []}
    return none
