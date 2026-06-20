"""M6j GET /stocks/{i}/history (backend-design ENDPOINTS §6.11). Auth-required, per-user; empty
(not 404) when the user has none; status derived from prediction_outcomes."""
import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo

_RJ = {"evidence": [{"text_en": "RSI bullish signal (100%)", "text_ko": "RSI 상승 신호 (100%)"}],
       "predicted_at": "2026-06-19T00:00:00Z", "entry_price": 84300.0}


async def _register(c, email="u@x.com"):
    r = await c.post("/auth/register", json={"email": email, "password": "Tr0ubadour9x"})
    d = r.json()["data"]
    return d["user"]["id"], d["access_token"]


async def _insert(uid, *, tf="5d", window="2026-06-26T00:00:00Z", direction="up"):
    async with connect(get_settings().sqlite_path) as con:
        s = await srepo.get_stock(con, "005930", "KRX")
        return await prepo.insert_prediction(
            con, user_id=uid, stock_id=s.id, timeframe=tf, direction=direction, confidence=66,
            reasoning_json=_RJ, model_version="5d-lr-20260620.1", window_closes_at=window)


@pytest.mark.asyncio
async def test_history_unauth_401(app_client):
    async with app_client as c:
        r = await c.get("/stocks/005930:KRX/history")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_history_unknown_symbol_404(app_client):
    async with app_client as c:
        _, token = await _register(c)
        r = await c.get("/stocks/ZZZZ:KRX/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "SYMBOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_history_empty_is_not_404(app_client):
    async with app_client as c:
        _, token = await _register(c)
        r = await c.get("/stocks/005930:KRX/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"] == {"instrument": "005930:KRX", "total": 0, "items": []}


@pytest.mark.asyncio
async def test_history_returns_user_item_pending(app_client):
    async with app_client as c:
        uid, token = await _register(c)
        await _insert(uid)
        r = await c.get("/stocks/005930:KRX/history", headers={"Authorization": f"Bearer {token}"})
    d = r.json()["data"]
    assert d["total"] == 1
    item = d["items"][0]
    assert item["status"] == "pending" and item["outcome"] is None
    assert item["evidence_summary_en"] == "RSI bullish signal (100%)"
    assert item["entry_price"] == 84300.0 and item["currency"] == "KRW"
    assert item["predicted_at"] == "2026-06-19T00:00:00Z"


@pytest.mark.asyncio
async def test_history_user_isolation(app_client):
    async with app_client as c:
        a_uid, a_tok = await _register(c, "a@x.com")
        b_uid, b_tok = await _register(c, "b@x.com")
        await _insert(a_uid)
        rb = await c.get("/stocks/005930:KRX/history", headers={"Authorization": f"Bearer {b_tok}"})
    assert rb.json()["data"]["total"] == 0      # B sees none of A's predictions


@pytest.mark.asyncio
async def test_history_status_filter_graded(app_client):
    async with app_client as c:
        uid, token = await _register(c)
        pid = await _insert(uid, window="2026-06-27T00:00:00Z")
        async with connect(get_settings().sqlite_path) as con:
            await con.execute(
                "INSERT INTO prediction_outcomes (prediction_id, actual_direction, "
                "actual_price_change_percent, marked_correct, exit_price) VALUES (?,?,?,?,?)",
                (pid, "up", 1.4, 1, 85500.0))
            await con.commit()
        r = await c.get("/stocks/005930:KRX/history?status=correct",
                        headers={"Authorization": f"Bearer {token}"})
    item = r.json()["data"]["items"][0]
    assert item["status"] == "correct"
    assert item["outcome"] == {"realized_direction": "up", "exit_price": 85500.0,
                               "move_pct": 1.4, "graded_at": item["outcome"]["graded_at"]}


@pytest.mark.asyncio
async def test_history_bad_param_400(app_client):
    async with app_client as c:
        _, token = await _register(c)
        h = {"Authorization": f"Bearer {token}"}
        bad_tf = await c.get("/stocks/005930:KRX/history?timeframe=2h", headers=h)
        bad_limit = await c.get("/stocks/005930:KRX/history?limit=999", headers=h)
    assert bad_tf.status_code == 400 and bad_limit.status_code == 400
