"""M5b training-set assembly (prediction-model.md §7.1/§7.3). Labels derive from the backfilled
technical_snapshots' `close` field (entry vs exit over the window); features come from the SAME
as-of-bounded builder used at serve time. Sampling stride = horizon (no overlapping labels)."""
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.ml.config import FEATURE_NAMES
from app.ml.dataset import build_dataset

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


def _redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def _seed(con, stock_id, interval, rows):
    for ts, close, rsi in rows:
        await trepo.upsert_snapshot(con, stock_id, interval, ts,
                                    {"close": close, "rsi_14": rsi, "macd_histogram": 1.0})


@pytest.mark.asyncio
async def test_build_dataset_labels_stride_and_move(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed(con, ref.id, "1d", [
            ("2026-05-01T06:30:00Z", 100.0, 50.0),
            ("2026-05-02T06:30:00Z", 100.5, 51.0),
            ("2026-05-03T06:30:00Z", 101.0, 55.0),   # exit for sample @0 -> +1.0% up
            ("2026-05-04T06:30:00Z", 99.0, 45.0),
            ("2026-05-05T06:30:00Z", 100.0, 50.0),   # exit for sample @2 -> -0.99% down
            ("2026-05-06T06:30:00Z", 102.0, 60.0),
            ("2026-05-07T06:30:00Z", 100.2, 50.0),   # exit for sample @4 -> +0.2% neutral
        ])
        samples = await build_dataset(con, _redis(), [ref], "2d")
    assert [s["label"] for s in samples] == ["up", "down", "neutral"]   # stride 2 -> entries 0,2,4
    assert samples[0]["move_pct"] == pytest.approx(1.0)
    assert samples[1]["move_pct"] == pytest.approx(-0.990099, abs=1e-4)
    assert samples[2]["move_pct"] == pytest.approx(0.2)
    assert [s["entry_ts"] for s in samples] == sorted(s["entry_ts"] for s in samples)  # chronological


@pytest.mark.asyncio
async def test_each_sample_carries_full_feature_vector(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed(con, ref.id, "1d", [
            ("2026-05-01T06:30:00Z", 100.0, 50.0),
            ("2026-05-03T06:30:00Z", 101.0, 55.0),
            ("2026-05-05T06:30:00Z", 102.0, 60.0),
        ])
        samples = await build_dataset(con, _redis(), [ref], "2d")
    assert samples, "expected at least one sample"
    for s in samples:
        assert list(s["features"].keys()) == FEATURE_NAMES
        assert s["features"]["market_is_krx"] == 1.0          # came from the real builder
        assert s["label"] in ("up", "down", "neutral")


@pytest.mark.asyncio
async def test_24h_uses_wallclock_exit(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        await _seed(con, ref.id, "1h", [
            ("2026-05-01T13:00:00Z", 100.0, 50.0),
            ("2026-05-01T14:00:00Z", 101.0, 51.0),
            ("2026-05-02T13:00:00Z", 105.0, 60.0),   # first snapshot >= entry + 24h
            ("2026-05-02T14:00:00Z", 106.0, 61.0),
        ])
        samples = await build_dataset(con, _redis(), [ref], "24h")
    assert len(samples) == 1                                  # stride ~1 session; only one fits
    assert samples[0]["exit_ts"] == "2026-05-02T13:00:00Z"    # wall-clock +24h, first at/after
    assert samples[0]["move_pct"] == pytest.approx(5.0)
    assert samples[0]["label"] == "up"


@pytest.mark.asyncio
async def test_no_samples_without_enough_future(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await _seed(con, ref.id, "1d", [("2026-05-01T06:30:00Z", 100.0, 50.0)])  # 1 bar, no exit
        samples = await build_dataset(con, _redis(), [ref], "2d")
    assert samples == []
