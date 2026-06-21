"""M7h/i public GET /stocks/{i}/accuracy (win-loss §8.2): no auth, cached, win-rate shape."""
import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.db.repositories import users as urepo

NOW = "2026-06-27T00:00:00Z"


async def _graded(*, direction="up", window, correct, tf="5d"):
    async with connect(get_settings().sqlite_path) as con:
        u = await urepo.get_by_email(con, "a@x.com") or await urepo.create_user(con, "a@x.com", "h", "en")
        s = await srepo.get_stock(con, "005930", "KRX")
        pid = await prepo.insert_prediction(
            con, user_id=u["id"], stock_id=s.id, timeframe=tf, direction=direction, confidence=66,
            reasoning_json={"entry_price": 100.0, "neutral_band_pct": 0.5},
            model_version="5d-lr-20260620.1", window_closes_at=window)
        await prepo.record_outcome(con, prediction_id=pid, actual_direction="up" if correct else "down",
                                   actual_price_change_percent=1.0, marked_correct=correct,
                                   exit_price=101.0, high_impact_event_overlap=0, checked_at_iso=NOW)


@pytest.mark.asyncio
async def test_accuracy_is_public_and_shaped(app_client):
    await _graded(direction="up", window="2026-06-26T00:00:00Z", correct=1)
    async with app_client as c:
        r = await c.get("/stocks/005930:KRX/accuracy")        # NO Authorization header
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["instrument"] == "005930:KRX" and d["window"] == "all"
    assert d["graded_total"] == 1 and d["low_sample"] is True
    assert d["directional"]["predictions"] == 1 and d["directional"]["wins"] == 1
    assert isinstance(d["by_timeframe"], list)
    assert r.json()["meta"]["cache"] == "miss"


@pytest.mark.asyncio
async def test_accuracy_cache_hit_on_second_call(app_client):
    await _graded(direction="up", window="2026-06-26T00:00:00Z", correct=1)
    async with app_client as c:
        first = await c.get("/stocks/005930:KRX/accuracy")
        second = await c.get("/stocks/005930:KRX/accuracy")
    assert first.json()["meta"]["cache"] == "miss"
    assert second.json()["meta"]["cache"] == "hit"
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_accuracy_unknown_symbol_404(app_client):
    async with app_client as c:
        r = await c.get("/stocks/ZZZZ:KRX/accuracy")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SYMBOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_accuracy_bad_params_400(app_client):
    async with app_client as c:
        bad_tf = await c.get("/stocks/005930:KRX/accuracy?timeframe=2h")
        bad_win = await c.get("/stocks/005930:KRX/accuracy?window=7d")
    assert bad_tf.status_code == 400 and bad_win.status_code == 400


@pytest.mark.asyncio
async def test_accuracy_timeframe_filter(app_client):
    await _graded(direction="up", window="2026-06-26T00:00:00Z", correct=1, tf="5d")
    await _graded(direction="up", window="2026-06-26T00:00:00Z", correct=0, tf="3d")
    async with app_client as c:
        r = await c.get("/stocks/005930:KRX/accuracy?timeframe=5d")
    d = r.json()["data"]
    assert d["graded_total"] == 1                       # only the 5d row
    assert [t["timeframe"] for t in d["by_timeframe"]] == ["5d"]
