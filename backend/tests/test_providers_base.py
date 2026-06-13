from datetime import datetime, timezone

from app.providers.base import PriceQuote, StockRef


def test_pricequote_and_stockref_construct():
    ref = StockRef(id=1, symbol="005930", exchange="KRX", region="KR",
                   currency="KRW", yfinance_ticker="005930.KS", finnhub_ticker=None)
    q = PriceQuote(price=84300.0, previous_close=83600.0, volume=11250300,
                   day_high=84600.0, day_low=83400.0,
                   as_of=datetime(2026, 6, 12, tzinfo=timezone.utc))
    assert ref.yfinance_ticker == "005930.KS"
    assert q.price == 84300.0 and q.as_of.tzinfo is timezone.utc
