"""M6i affects-your-stocks matching (economic-calendar §9). Precedence: stock > sector > market."""
from app.calendar.affects import compute_event_affects

SECTORS = {"semiconductors": {"members": ["NVDA", "005930:KRX", "000660:KRX"]},
           "autos": {"members": ["005380:KRX", "TSLA"]}}


def _aff(stocks=None, sectors=None, indexes=None):
    return {"stocks": stocks or [], "sectors": sectors or [], "indexes": indexes or []}


def test_stock_match():
    out = compute_event_affects([("005930", "KRX")],
                                _aff(stocks=[{"symbol": "005930", "exchange": "KRX"}]), SECTORS)
    assert out == {"affects_your_stocks": True, "match_level": "stock",
                   "matched_symbols": ["005930:KRX"]}


def test_sector_match_no_symbols():
    out = compute_event_affects([("000660", "KRX")],
                                _aff(sectors=[{"code": "semiconductors"}]), SECTORS)
    assert out["match_level"] == "sector" and out["matched_symbols"] == []


def test_market_match_krx_and_us():
    kr = compute_event_affects([("005930", "KRX")], _aff(indexes=["KOSPI"]), SECTORS)
    us = compute_event_affects([("AAPL", "NASDAQ")], _aff(indexes=["SP500", "NASDAQ_COMPOSITE"]), SECTORS)
    assert kr["match_level"] == "market" and us["match_level"] == "market"


def test_precedence_stock_beats_sector_beats_market():
    out = compute_event_affects(
        [("005930", "KRX")],
        _aff(stocks=[{"symbol": "005930", "exchange": "KRX"}],
             sectors=[{"code": "semiconductors"}], indexes=["KOSPI"]), SECTORS)
    assert out["match_level"] == "stock"


def test_no_match_returns_false():
    out = compute_event_affects([("AAPL", "NASDAQ")], _aff(indexes=["KOSPI"]), SECTORS)
    assert out == {"affects_your_stocks": False, "match_level": None, "matched_symbols": []}


def test_none_or_empty_inputs():
    assert compute_event_affects([("AAPL", "NASDAQ")], None, SECTORS)["affects_your_stocks"] is False
    assert compute_event_affects([], _aff(indexes=["KOSPI"]), SECTORS)["affects_your_stocks"] is False


def test_indexes_accept_dict_or_string_shape():
    # registry stores indexes as bare strings; earnings/other paths may use {code}. Handle both.
    out = compute_event_affects([("005930", "KRX")], _aff(indexes=[{"code": "KOSPI"}]), SECTORS)
    assert out["match_level"] == "market"
