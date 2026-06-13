from datetime import datetime, timezone

from app.market.hours import market_state


def _utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_krx_open_friday_midsession():
    # 2026-06-12 is a Friday. 05:00 UTC = 14:00 KST -> open.
    assert market_state("KRX", _utc(2026, 6, 12, 5, 0)) == "open"


def test_krx_closed_outside_session():
    # 07:00 UTC = 16:00 KST (after 15:30 close) -> closed.
    assert market_state("KRX", _utc(2026, 6, 12, 7, 0)) == "closed"


def test_krx_closed_weekend():
    # 2026-06-13 is a Saturday.
    assert market_state("KRX", _utc(2026, 6, 13, 5, 0)) == "closed"


def test_nyse_states():
    # 2026-06-12 Friday. ET = UTC-4 (EDT in June).
    assert market_state("NYSE", _utc(2026, 6, 12, 14, 0)) == "open"   # 10:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 12, 0)) == "pre"    # 08:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 21, 0)) == "post"   # 17:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 2, 0)) == "closed"  # 22:00 ET (Thu)


def test_unknown_exchange_closed():
    assert market_state("OTC", _utc(2026, 6, 12, 14, 0)) == "closed"
