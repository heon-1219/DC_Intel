from datetime import datetime, timezone

import pandas as pd
import pytest

from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers import yfinance_bars as mod
from app.providers.yfinance_bars import YFinanceBarProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


def test_normalize_lowercases_selects_and_utc():
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    idx = pd.to_datetime(["2026-06-10", "2026-06-11"]).tz_localize("UTC")
    raw = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [0, 1],
                        "Close": [1.5, 2.5], "Volume": [10, 20],
                        "Dividends": [0, 0]}, index=idx)
    out = mod._normalize(raw, "1d", now)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert str(out.index.tz) == "UTC"
    assert len(out) == 2   # both daily bars completed (last is 06-11, now is 06-12)


def test_normalize_drops_currently_forming_last_bar():
    now = datetime(2026, 6, 12, 10, 2, tzinfo=timezone.utc)
    # last 5-min bar starts 10:00; it closes at 10:05 > now -> still forming -> dropped.
    idx = pd.to_datetime(["2026-06-12 09:50", "2026-06-12 09:55",
                          "2026-06-12 10:00"]).tz_localize("UTC")
    raw = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
                        "Close": [1, 2, 3], "Volume": [1, 1, 1]}, index=idx)
    out = mod._normalize(raw, "5m", now)
    assert len(out) == 2
    assert out.index[-1] == pd.Timestamp("2026-06-12 09:55", tz="UTC")


def test_normalize_empty_frame_returns_empty():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    out = mod._normalize(pd.DataFrame(), "1d", now)
    assert out.empty


@pytest.mark.asyncio
async def test_fetch_bars_wraps_errors_as_providererror(monkeypatch):
    def boom(ticker, interval, days, now):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(mod.YFinanceBarProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await YFinanceBarProvider().fetch_bars(REF, "1d")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fetch_bars_daily():
    bars = await YFinanceBarProvider().fetch_bars(REF, "1d")
    assert not bars.empty
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert str(bars.index.tz) == "UTC"
    assert len(bars) > 200   # ~3y of daily bars -> EMA200 computable
