import pytest

from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers.pykrx_provider import PykrxProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


@pytest.mark.asyncio
async def test_pykrx_wraps_errors(monkeypatch):
    import app.providers.pykrx_provider as mod

    def boom(symbol):
        raise RuntimeError("krx down")

    monkeypatch.setattr(mod.PykrxProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await PykrxProvider().fetch_quote(REF)


@pytest.mark.live
@pytest.mark.asyncio
async def test_pykrx_live():
    q = await PykrxProvider().fetch_quote(REF)
    assert q.price > 0
