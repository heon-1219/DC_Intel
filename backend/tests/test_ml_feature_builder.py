"""M5 feature builder tests (prediction-model.md §4.2). Seeds a real temp SQLite DB + fakeredis
and asserts the exact 15-feature vector, missing/stale flags, and — critically — as-of bounding
(no record after as_of may influence the vector; the #1 anti-leakage guard)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import cross_market_bars as cmrepo
from app.db.repositories import sentiment_logs as slrepo
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.ml.config import FEATURE_NAMES
from app.ml.features.builder import build_features

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


def _redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _payload(**kw):
    """Minimal indicators payload carrying only the keys the feature builder reads."""
    base = {"rsi_14": None, "ema_5_20_cross_dir": 0, "bars_since_ema_5_20_cross": 20,
            "macd_histogram": None, "close": None, "bb_percent_b": None, "vol_z20": None}
    base.update(kw)
    return base


async def _ins_event(con, *, name, time, impact, country, etype, status="scheduled"):
    await con.execute(
        "INSERT INTO economic_events (event_name,event_time,impact_level,country,event_type,"
        "provider,status) VALUES (?,?,?,?,?,?,?)",
        (name, time, impact, country, etype, "seed", status))
    await con.commit()


# --- technical features ----------------------------------------------------

@pytest.mark.asyncio
async def test_technical_features_and_as_of_bounding(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        # four consecutive daily snapshots t-3..t (interval 1d feeds the 2d model)
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-08T06:30:00Z",
                                    _payload(rsi_14=40.0, macd_histogram=2.0, close=100.0))
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-09T06:30:00Z",
                                    _payload(rsi_14=45.0, macd_histogram=3.0, close=100.0))
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-10T06:30:00Z",
                                    _payload(rsi_14=55.0, macd_histogram=4.0, close=100.0))
        await trepo.upsert_snapshot(
            con, ref.id, "1d", "2026-06-11T06:30:00Z",
            _payload(rsi_14=58.0, ema_5_20_cross_dir=1, bars_since_ema_5_20_cross=3,
                     macd_histogram=5.0, close=100.0, bb_percent_b=0.8, vol_z20=1.2))
        # a FUTURE snapshot that must be ignored (as-of bounding)
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-13T06:30:00Z",
                                    _payload(rsi_14=99.0, close=100.0, macd_histogram=9.0))
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")

    assert vec["rsi_14"] == 58.0                      # latest <= as_of, not the 99.0 future bar
    assert vec["rsi_slope_3"] == pytest.approx(58.0 - 40.0)   # rsi[t] - rsi[t-3]
    assert vec["ema_cross_state"] == 1
    assert vec["ema_bars_since_cross"] == pytest.approx(3.0)  # bars_since * sign(cross_dir)
    assert vec["macd_hist_norm"] == pytest.approx(5.0 / 100.0)
    assert vec["macd_hist_delta"] == pytest.approx(5.0 / 100.0 - 4.0 / 100.0)  # normalized cross-bar
    assert vec["bb_position"] == pytest.approx(0.8)
    assert vec["vol_z20"] == pytest.approx(1.2)
    for k in ("rsi_14", "rsi_slope_3", "ema_cross_state", "ema_bars_since_cross",
              "macd_hist_norm", "macd_hist_delta", "bb_position", "vol_z20"):
        assert meta["missing"][k] is False


@pytest.mark.asyncio
async def test_ema_bars_since_cross_is_signed_down(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(
            con, ref.id, "1d", "2026-06-11T06:30:00Z",
            _payload(rsi_14=30.0, ema_5_20_cross_dir=-1, bars_since_ema_5_20_cross=5,
                     macd_histogram=-1.0, close=50.0))
        vec, _ = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
    assert vec["ema_cross_state"] == -1
    assert vec["ema_bars_since_cross"] == pytest.approx(-5.0)   # down-cross -> negative


@pytest.mark.asyncio
async def test_bb_position_is_clipped(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-11T06:30:00Z",
                                    _payload(rsi_14=50.0, close=50.0, bb_percent_b=2.3))
        hi, _ = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-11T06:30:00Z",
                                    _payload(rsi_14=50.0, close=50.0, bb_percent_b=-1.4))
        lo, _ = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
    assert hi["bb_position"] == pytest.approx(1.5)     # clip upper
    assert lo["bb_position"] == pytest.approx(-0.5)    # clip lower


@pytest.mark.asyncio
async def test_slope_and_delta_missing_with_thin_history(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-11T06:30:00Z",
                                    _payload(rsi_14=58.0, macd_histogram=5.0, close=100.0))
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
    assert vec["rsi_14"] == 58.0                       # present
    assert vec["macd_hist_norm"] == pytest.approx(0.05)
    assert vec["rsi_slope_3"] is None and meta["missing"]["rsi_slope_3"] is True
    assert vec["macd_hist_delta"] is None and meta["missing"]["macd_hist_delta"] is True


@pytest.mark.asyncio
async def test_technical_missing_when_no_snapshot(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
    for k in ("rsi_14", "ema_cross_state", "macd_hist_norm", "bb_position", "vol_z20"):
        assert vec[k] is None and meta["missing"][k] is True


# --- sentiment features ----------------------------------------------------

@pytest.mark.asyncio
async def test_sentiment_agg_and_delta(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await slrepo.insert_log(con, ref.id, "2026-06-11T22:00:00Z", 10.0,
                                {"timeframe_scores": {"2d": {"score": 10.0, "low_confidence": False}}})
        await slrepo.insert_log(con, ref.id, "2026-06-12T00:00:00Z", 40.0,
                                {"timeframe_scores": {"2d": {"score": 40.0, "low_confidence": False}}})
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["sent_agg"] == pytest.approx(0.40)               # score/100 -> [-1,1]
    assert vec["sent_delta_2h"] == pytest.approx(0.40 - 0.10)   # vs now-2h
    assert meta["missing"]["sent_agg"] is False


@pytest.mark.asyncio
async def test_sentiment_missing_on_low_confidence(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await slrepo.insert_log(con, ref.id, "2026-06-12T00:00:00Z", 40.0,
                                {"timeframe_scores": {"2d": {"score": 40.0, "low_confidence": True}}})
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["sent_agg"] is None and meta["missing"]["sent_agg"] is True


@pytest.mark.asyncio
async def test_sentiment_missing_on_null_score(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await slrepo.insert_log(con, ref.id, "2026-06-12T00:00:00Z", None,
                                {"timeframe_scores": {"2d": {"score": None, "low_confidence": False}}})
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["sent_agg"] is None and meta["missing"]["sent_agg"] is True


# --- econ features ---------------------------------------------------------

@pytest.mark.asyncio
async def test_econ_high_impact_and_score_inside_window(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")   # region KR -> relevant {KR, US}
        # high-impact US event 18h after as_of -> inside the 2d (48h) window
        await _ins_event(con, name="US CPI", time="2026-06-12T18:00:00Z", impact="high",
                         country="US", etype="us_cpi")
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["econ_high_impact_6h"] == pytest.approx(1.0)
    assert vec["econ_impact_score"] == pytest.approx(3.0)        # weight high=3 * proximity 1
    assert meta["missing"]["econ_high_impact_6h"] is False
    ev = meta["high_impact_events"][0]
    assert ev["impact"] == "high" and ev["relation"] == "inside_window"   # §8.1 temporal relation
    assert ev["title_en"] == "US CPI" and ev["country"] == "US"


@pytest.mark.asyncio
async def test_econ_proximity_decay_before_window(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        # high event 3h BEFORE as_of -> outside window, gap 3h -> proximity 1-3/6 = 0.5
        await _ins_event(con, name="US Jobs", time="2026-06-11T21:00:00Z", impact="high",
                         country="US", etype="us_jobs")
        vec, _ = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["econ_high_impact_6h"] == pytest.approx(1.0)      # within [as_of-6h, ...]
    assert vec["econ_impact_score"] == pytest.approx(3.0 * 0.5)  # decayed


@pytest.mark.asyncio
async def test_econ_irrelevant_country_excluded(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")   # {KR, US} -> JP not relevant
        await _ins_event(con, name="JP BOJ", time="2026-06-12T05:00:00Z", impact="high",
                         country="JP", etype="jp_boj")
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["econ_high_impact_6h"] == pytest.approx(0.0)
    assert vec["econ_impact_score"] == pytest.approx(0.0)
    assert meta["missing"]["econ_high_impact_6h"] is False      # 0 is a real value, not missing


# --- aux + cross-market + staleness ---------------------------------------

@pytest.mark.asyncio
async def test_market_is_krx_flag(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        kr = await srepo.get_stock(con, "005930", "KRX")
        us = await srepo.get_stock(con, "AAPL", "NASDAQ")
        vkr, _ = await build_features(con, _redis(), kr, "2d", "2026-06-12T00:00:00Z")
        vus, _ = await build_features(con, _redis(), us, "2d", "2026-06-12T00:00:00Z")
    assert vkr["market_is_krx"] == pytest.approx(1.0)
    assert vus["market_is_krx"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_cross_market_missing_when_no_ref_bars(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")   # ref SOXX, but no bars stored
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    for k in ("xmkt_ref_return", "xmkt_corr_60d"):
        assert vec[k] is None and meta["missing"][k] is True


@pytest.mark.asyncio
async def test_xmkt_ref_return_computed_and_leak_safe(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")   # -> SOXX (US, closes 20:00Z)
        await cmrepo.upsert_bars(con, "SOXX", [
            ("2026-06-10", 225.0), ("2026-06-11", 223.0),
            ("2026-06-12", 999.0)])   # 06-12 US session NOT closed by a KRX-morning t0 -> must be ignored
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:30:00Z")
    assert vec["xmkt_ref_return"] == pytest.approx((223.0 - 225.0) / 225.0 * 100)  # 06-11 vs 06-10
    assert meta["missing"]["xmkt_ref_return"] is False


@pytest.mark.asyncio
async def test_xmkt_corr_computed_with_enough_history(tmp_path):
    db = await _db(tmp_path)
    dates = [(datetime(2026, 4, 1, tzinfo=timezone.utc) + timedelta(days=i)).date().isoformat()
             for i in range(40)]
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        # stock daily closes (1d snapshots) + SOXX bars on the same dates, co-moving -> corr defined
        await cmrepo.upsert_bars(con, "SOXX", [(d, 200.0 + 2 * i) for i, d in enumerate(dates)])
        for i, d in enumerate(dates):
            await trepo.upsert_snapshot(con, ref.id, "1d", d + "T06:30:00Z",
                                        _payload(rsi_14=50.0, close=100.0 + i))
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-05-25T00:30:00Z")
    assert vec["xmkt_corr_60d"] is not None and -1.0 <= vec["xmkt_corr_60d"] <= 1.0
    assert meta["missing"]["xmkt_corr_60d"] is False


@pytest.mark.asyncio
async def test_intraday_technicals_stale_flag(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        # 24h model uses 1h bars; a snapshot 3h old exceeds bar(1h)+grace(15m) -> stale
        await trepo.upsert_snapshot(con, ref.id, "1h", "2026-06-12T01:00:00Z",
                                    _payload(rsi_14=55.0, close=100.0, macd_histogram=1.0))
        vec, meta = await build_features(con, _redis(), ref, "24h", "2026-06-12T04:00:00Z")
    assert vec["rsi_14"] == 55.0                # value still emitted
    assert meta["stale"]["rsi_14"] is True
    assert meta["any_stale"] is True


@pytest.mark.asyncio
async def test_fresh_daily_technicals_not_stale(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        # 1d bar 13.5h old is fresh for a daily model (bar 1d + grace), NOT stale
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-11T06:30:00Z",
                                    _payload(rsi_14=55.0, close=100.0, macd_histogram=1.0))
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-11T20:00:00Z")
    assert meta["stale"]["rsi_14"] is False
    assert meta["any_stale"] is False


class _FailingRedis:
    async def get(self, *_a, **_k):
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_builder_tolerates_redis_failure(tmp_path):
    # econ staleness reads cal:last_synced_at; a Redis outage must not crash the builder.
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        vec, meta = await build_features(con, _FailingRedis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert vec["econ_high_impact_6h"] == 0.0          # still computed
    assert meta["stale"]["econ_high_impact_6h"] is False   # can't check freshness -> not penalized


@pytest.mark.asyncio
async def test_vector_has_all_15_features(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        vec, meta = await build_features(con, _redis(), ref, "2d", "2026-06-12T00:00:00Z")
    assert list(vec.keys()) == FEATURE_NAMES          # exact contract order
    assert set(meta["missing"].keys()) == set(FEATURE_NAMES)
