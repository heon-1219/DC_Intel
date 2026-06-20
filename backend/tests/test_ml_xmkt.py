"""M5d cross-market math (prediction-model.md §4.2 #13/#14, §4.3). Pure functions: reference
resolution, leak-safe 'latest completed session' cutoff, ref return, 60-day return correlation."""
import pytest

from app.ml.xmkt import (compute_corr, compute_ref_return, cutoff_date, daily_returns,
                         reference_exchange, resolve_reference)


@pytest.mark.parametrize("stored,expected", [
    ("SOXX", "SOXX"), ("^N225", "^N225"), ("SPY", "SPY"),
    ("005490:KRX", "005490.KS"),     # instrument format -> yfinance .KS
    ("", "SPY"), (None, "SPY"),      # no mapping -> SPY fallback (§4.3)
])
def test_resolve_reference(stored, expected):
    assert resolve_reference(stored) == expected


@pytest.mark.parametrize("ref,exch", [
    ("^N225", "JP"), ("005490.KS", "KR"), ("^KS11", "KR"),
    ("SOXX", "US"), ("SPY", "US"), ("MU", "US"),
])
def test_reference_exchange(ref, exch):
    assert reference_exchange(ref) == exch


@pytest.mark.parametrize("as_of,exch,expected", [
    ("2026-06-12T00:30:00Z", "US", "2026-06-11"),   # KRX morning: prior US session is last completed
    ("2026-06-12T21:00:00Z", "US", "2026-06-12"),   # after US close -> same-day session completed
    ("2026-06-12T08:00:00Z", "JP", "2026-06-12"),   # after Tokyo close (06:00Z) -> same day
    ("2026-06-12T05:00:00Z", "JP", "2026-06-11"),   # before Tokyo close -> prior day
])
def test_cutoff_date_is_leak_safe(as_of, exch, expected):
    assert cutoff_date(as_of, exch) == expected


def test_compute_ref_return():
    # newest-first closes; return over the latest completed session
    out = compute_ref_return([("2026-06-11", 223.0), ("2026-06-10", 225.0)])
    assert out == pytest.approx((223.0 - 225.0) / 225.0 * 100)
    assert compute_ref_return([("2026-06-11", 223.0)]) is None     # need 2 closes


def test_daily_returns():
    r = daily_returns([("2026-06-09", 100.0), ("2026-06-10", 110.0), ("2026-06-11", 99.0)])
    assert r == {"2026-06-10": pytest.approx(0.10), "2026-06-11": pytest.approx(-0.10)}


def test_compute_corr_perfect_and_anti():
    stock = [("2026-06-09", 100.0), ("2026-06-10", 110.0), ("2026-06-11", 121.0),
             ("2026-06-12", 108.9)]
    same = [("2026-06-09", 50.0), ("2026-06-10", 55.0), ("2026-06-11", 60.5), ("2026-06-12", 54.45)]
    anti = [("2026-06-09", 50.0), ("2026-06-10", 45.0), ("2026-06-11", 40.5), ("2026-06-12", 45.0)]
    assert compute_corr(stock, same, window=60, min_overlap=2) == pytest.approx(1.0, abs=1e-9)
    assert compute_corr(stock, anti, window=60, min_overlap=2) < 0


def test_compute_corr_insufficient_overlap_is_none():
    stock = [("2026-06-10", 100.0), ("2026-06-11", 101.0)]
    ref = [("2026-06-10", 50.0), ("2026-06-11", 51.0)]
    assert compute_corr(stock, ref, window=60, min_overlap=30) is None   # only 1 aligned return
