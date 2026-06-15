"""Build affected_stocks_json static block (economic-calendar.md §6). The history block
(§8) is written later by the M3c event-study job; it is None here."""
from app.calendar.registry import sector_codes_for


def build_affected_json(entry: dict | None, sectors: dict, *,
                        earnings_stock: tuple[str, str] | None = None) -> dict:
    if earnings_stock is not None:
        sym, exch = earnings_stock
        secs = [{"code": c} for c in sector_codes_for(sectors, sym, exch)]
        return {
            "scope": "stock", "indexes": [], "sectors": secs,
            "stocks": [{"symbol": sym, "exchange": exch, "relation": "direct"}],
            "history": None,
        }
    aff = (entry or {}).get("affected", {}) or {}
    stocks = aff.get("stocks", []) or []
    return {
        "scope": "stock" if stocks else "macro",
        "indexes": aff.get("indexes", []) or [],
        "sectors": aff.get("sectors", []) or [],
        "stocks": stocks,
        "history": None,
    }
