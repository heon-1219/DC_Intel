import re

# Addressable exchanges (schema.md §1.5; INDEX is intentionally not addressable).
_VALID_EXCHANGES = {"KRX", "NASDAQ", "NYSE", "AMEX", "OTC"}
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


class InvalidInstrument(ValueError):
    pass


def parse_instrument(raw: str) -> tuple[str, str]:
    """'{symbol}:{exchange}' -> (SYMBOL, EXCHANGE), uppercased. Raises InvalidInstrument."""
    if raw.count(":") != 1:
        raise InvalidInstrument(raw)
    symbol, exchange = raw.split(":", 1)
    symbol, exchange = symbol.strip().upper(), exchange.strip().upper()
    if not _SYMBOL_RE.match(symbol) or exchange not in _VALID_EXCHANGES:
        raise InvalidInstrument(raw)
    return symbol, exchange
