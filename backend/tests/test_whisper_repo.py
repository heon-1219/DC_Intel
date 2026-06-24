from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import whisper as repo
from app.intel.whisper.models import WhisperResult

MIG = str(Path(__file__).resolve().parents[1] / "migrations")


async def _db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    async with connect(db) as con:
        await con.execute(
            "INSERT INTO stocks (symbol, exchange, region, company_name, yfinance_ticker) "
            "VALUES ('NVDA','NASDAQ','US','NVIDIA Corp','NVDA')")
        await con.commit()
    return db


def _result(value=1.43, status="corroborated", reason=None, conf=80):
    return WhisperResult(
        whisper_value=value, confidence=conf, status=status, anchor=1.40,
        surprise_vs_anchor=(round(value - 1.40, 4) if value is not None else None),
        inlier_dispersion=0.01, n_inliers=3, n_outliers_rejected=1, n_distinct_families=3,
        contributing_families=("earningswhispers", "estimize", "websearch"),
        factors={"f_count": 1.0, "caps": []}, rounds_used=2, abstain_reason=reason,
        computed_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_upsert_and_get_latest(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_result(con, stock_id=1, earnings_event_id=None,
                                 earnings_date=date(2026, 7, 1), result=_result())
        row = await repo.get_latest_for_stock(con, 1)
    assert row is not None
    assert row["status"] == "corroborated"
    assert row["whisper_value"] == 1.43
    assert row["anchor"] == 1.40
    assert row["contributing_families"] == ["earningswhispers", "estimize", "websearch"]
    assert row["factors"]["caps"] == []
    assert row["abstain_reason"] is None
    assert row["earnings_date"] == "2026-07-01"


@pytest.mark.asyncio
async def test_upsert_overwrites_same_stock_and_date(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_result(con, stock_id=1, earnings_event_id=None,
                                 earnings_date=date(2026, 7, 1), result=_result(value=1.40, conf=60))
        # a denser-near-the-date rerun produces a stronger corroboration for the SAME report
        await repo.upsert_result(con, stock_id=1, earnings_event_id=None,
                                 earnings_date=date(2026, 7, 1), result=_result(value=1.45, conf=85))
        rows = await repo.list_for_stock(con, 1)
    assert len(rows) == 1                    # collapsed on (stock_id, earnings_date)
    assert rows[0]["whisper_value"] == 1.45
    assert rows[0]["confidence"] == 85


@pytest.mark.asyncio
async def test_abstention_is_persisted_as_first_class_row(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_result(con, stock_id=1, earnings_event_id=None,
                                 earnings_date=date(2026, 7, 1),
                                 result=_result(value=None, status="no_reliable_whisper",
                                                reason="NO_OBSERVATIONS", conf=0))
        row = await repo.get_latest_for_stock(con, 1)
    assert row["status"] == "no_reliable_whisper"
    assert row["whisper_value"] is None
    assert row["abstain_reason"] == "NO_OBSERVATIONS"
    assert row["surprise_vs_anchor"] is None


@pytest.mark.asyncio
async def test_get_latest_returns_newest_by_computed_at(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        await repo.upsert_result(
            con, stock_id=1, earnings_event_id=None, earnings_date=date(2026, 7, 1),
            result=WhisperResult(
                whisper_value=1.41, confidence=60, status="tentative", anchor=1.40,
                surprise_vs_anchor=0.01, inlier_dispersion=0.0, n_inliers=1, n_outliers_rejected=0,
                n_distinct_families=1, contributing_families=("earningswhispers",), factors={},
                rounds_used=1, abstain_reason=None,
                computed_at=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)))
        await repo.upsert_result(
            con, stock_id=1, earnings_event_id=None, earnings_date=date(2026, 8, 1),
            result=_result(value=2.10))   # later report, more recent computed_at
        row = await repo.get_latest_for_stock(con, 1)
    assert row["earnings_date"] == "2026-08-01"
    assert row["whisper_value"] == 2.10


@pytest.mark.asyncio
async def test_get_latest_none_when_absent(tmp_path):
    db = await _db(tmp_path)
    async with connect(db) as con:
        assert await repo.get_latest_for_stock(con, 1) is None
