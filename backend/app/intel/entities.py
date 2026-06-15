"""Ticker/entity extraction (market-intel-pipeline.md §4.2). Cashtags ($AAPL, $삼성전자) +
resolution to a stocks row. Plain uppercase words are intentionally NOT treated as tickers
(too many false positives); cashtags are the precise signal."""
import re

_CASHTAG = re.compile(r"\$([A-Za-z]{1,6}|[가-힣]{2,10})")


def extract_cashtags(text: str) -> list[str]:
    """Distinct cashtag symbols, latin upper-cased, order-preserving."""
    out: list[str] = []
    for m in _CASHTAG.findall(text or ""):
        sym = m.upper() if m.isascii() else m
        if sym not in out:
            out.append(sym)
    return out


def resolve_symbol(symbol: str, by_symbol: dict, by_name_ko: dict):
    """Map a cashtag to a stocks row id. by_symbol keyed by upper symbol; by_name_ko keyed by
    Korean company name. Returns stock_id or None (None => market-wide intel)."""
    if symbol in by_symbol:
        return by_symbol[symbol]
    return by_name_ko.get(symbol)
