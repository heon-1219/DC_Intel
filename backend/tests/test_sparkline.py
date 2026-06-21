"""M8g — intraday sparkline helper (backend-design §6.7)."""
import pandas as pd
import pytest

from app.services.sparkline import build_sparkline


def _df():
    idx = pd.to_datetime([
        "2026-06-12T06:00:00Z", "2026-06-12T06:05:00Z",          # prior session (drop)
        "2026-06-15T00:00:00Z", "2026-06-15T00:05:00Z", "2026-06-15T00:10:00Z",  # last session
    ], utc=True)
    return pd.DataFrame({"close": [10.0, 11.0, 20.0, 21.0, 22.0]}, index=idx)


class _FakeBars:
    def __init__(self, df):
        self._df = df

    async def fetch_bars(self, ref, interval):
        assert interval == "5m"
        return self._df


class _ErrBars:
    async def fetch_bars(self, ref, interval):
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_returns_last_session_oldest_to_newest():
    out = await build_sparkline(_FakeBars(_df()), ref=None)
    assert out == [20.0, 21.0, 22.0]   # only the 06-15 session, most-recent last


@pytest.mark.asyncio
async def test_caps_at_max_points_keeping_most_recent():
    out = await build_sparkline(_FakeBars(_df()), ref=None, max_points=2)
    assert out == [21.0, 22.0]


@pytest.mark.asyncio
async def test_error_degrades_to_empty():
    assert await build_sparkline(_ErrBars(), ref=None) == []


@pytest.mark.asyncio
async def test_empty_frame_returns_empty():
    out = await build_sparkline(_FakeBars(pd.DataFrame({"close": []})), ref=None)
    assert out == []
