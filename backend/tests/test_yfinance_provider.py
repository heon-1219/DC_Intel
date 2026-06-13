import pytest

from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers.yfinance_provider import YFinanceProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


@pytest.mark.asyncio
async def test_wraps_upstream_errors_as_providererror(monkeypatch):
    import app.providers.yfinance_provider as mod

    def boom(ticker):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(mod.YFinanceProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await YFinanceProvider().fetch_quote(REF)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fetch_samsung():
    q = await YFinanceProvider().fetch_quote(REF)
    assert q.price > 0 and q.as_of is not None
