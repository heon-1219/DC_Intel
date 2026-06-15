from app.intel.entities import extract_cashtags, resolve_symbol


def test_extract_cashtags_latin_and_korean():
    tags = extract_cashtags("Loading up on $AAPL and $nvda, also $삼성전자 today $AAPL")
    assert tags == ["AAPL", "NVDA", "삼성전자"]   # upper latin, dedup, order preserved


def test_extract_cashtags_none():
    assert extract_cashtags("no tickers here, just prices going up") == []


def test_resolve_symbol():
    by_symbol = {"AAPL": 5, "NVDA": 6}
    by_name_ko = {"삼성전자": 1}
    assert resolve_symbol("AAPL", by_symbol, by_name_ko) == 5
    assert resolve_symbol("삼성전자", by_symbol, by_name_ko) == 1
    assert resolve_symbol("ZZZZ", by_symbol, by_name_ko) is None   # market-wide
