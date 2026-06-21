"""M6h GET /stocks/{i}/predict (backend-design ENDPOINTS §6.5). Auth-required; serves only the
gate-passed 5d (others -> 503 MODEL_UNAVAILABLE, the disabled-with-note core); inserts an audit row."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis.aioredis
import httpx
import joblib
import pytest

pytest.importorskip("sklearn")
from sklearn.linear_model import LogisticRegression          # noqa: E402
from sklearn.preprocessing import StandardScaler             # noqa: E402

from app.db.migrate import migrate                           # noqa: E402
from app.db.seed import seed_stocks                          # noqa: E402
from app.ml.calibrate import fit_calibrators                 # noqa: E402
from app.ml.config import FEATURE_NAMES                      # noqa: E402

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


def _write_5d_artifact(model_dir: str):
    X, y = [], []
    for i in range(150):
        r = (i * 13) % 100
        y.append("up" if r >= 60 else ("down" if r < 40 else "neutral"))
        row = [0.0] * 15
        row[0] = float(r)
        X.append(row)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    clf = LogisticRegression(max_iter=2000, random_state=0).fit(Xs, y)
    raw = [{c: float(p) for c, p in zip(clf.classes_, clf.predict_proba([Xs[i]])[0])}
           for i in range(len(X))]
    cals = fit_calibrators(raw, y, n_val=len(X))
    d = Path(model_dir) / "5d" / "5d-lr-20260620.1"
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, d / "model.pkl")
    joblib.dump(scaler, d / "scaler.pkl")
    joblib.dump(cals, d / "calibrators.pkl")
    (d / "manifest.json").write_text(json.dumps({
        "model_version": "5d-lr-20260620.1", "algorithm": "logistic", "created_at": "2026-06-20T00:00:00Z",
        "tau_dir": 0.45, "staleness_confidence_cap": 65, "neutral_band_pct": 0.5,
        "gate": {"passed": True},
        "features": [{"name": n, "mean": float(scaler.mean_[i]), "std": float(scaler.scale_[i])}
                     for i, n in enumerate(FEATURE_NAMES)]}), encoding="utf-8")


@pytest.fixture
def predict_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    from app.config import get_settings
    get_settings.cache_clear()
    migrate(get_settings().sqlite_path, MIG)
    seed_stocks(get_settings().sqlite_path, CSV)
    _write_5d_artifact(get_settings().model_dir)

    import app.cache.redis as cache_redis
    from app.ml.serving import loader
    loader.clear_cache()
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_redis, "get_client", lambda: fake)

    from app.main import create_app
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://test"), fake


async def _token(c):
    r = await c.post("/auth/register", json={"email": "u@x.com", "password": "Tr0ubadour9x"})
    return r.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_predict_requires_auth(predict_client):
    client, _ = predict_client
    async with client as c:
        r = await c.get("/stocks/005930:KRX/predict?timeframe=5d")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_predict_bad_timeframe_400(predict_client):
    client, _ = predict_client
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        r = await c.get("/stocks/005930:KRX/predict?timeframe=2h", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PARAM"


@pytest.mark.asyncio
async def test_predict_unknown_symbol_404(predict_client):
    client, _ = predict_client
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        r = await c.get("/stocks/ZZZZ:KRX/predict?timeframe=5d", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "SYMBOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_predict_disabled_timeframe_503(predict_client):
    client, _ = predict_client
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        r = await c.get("/stocks/005930:KRX/predict?timeframe=1h", headers=h)   # not gate-passed
    body = r.json()
    assert r.status_code == 503 and body["error"]["code"] == "MODEL_UNAVAILABLE"
    assert body["error"]["details"]["available_timeframes"] == ["5d"]


@pytest.mark.asyncio
async def test_predict_5d_happy_path_and_audit_insert(predict_client):
    client, fake = predict_client
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        await fake.set("px:quote:005930:KRX", json.dumps(
            {"price": 84300.0, "previous_close": 83000.0, "as_of": now, "currency": "KRW"}))
        r = await c.get("/stocks/005930:KRX/predict?timeframe=5d", headers=h)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["prediction_id"] and d["timeframe"] == "5d"
    assert d["direction"] in ("up", "down", "neutral") and 0 <= d["confidence"] <= 100
    assert d["entry_price"] == 84300.0 and d["currency"] == "KRW"
    assert d["model_version"] == "5d-lr-20260620.1"
    assert "evidence_summary_en" in d and isinstance(d["evidence"], list)
    assert r.json()["meta"]["source"] == "model"

    # audit row persisted
    from app.config import get_settings
    from app.db.connection import connect
    async with connect(get_settings().sqlite_path) as con:
        cur = await con.execute("SELECT COUNT(*) AS c FROM predictions WHERE id=?", (d["prediction_id"],))
        assert (await cur.fetchone())["c"] == 1


@pytest.mark.asyncio
async def test_predict_stale_price_in_market_hours_503(predict_client, monkeypatch):
    """§9.4: market open + price >30min old -> 503 SOURCE_DEGRADED (no pred cache to fall back on)."""
    monkeypatch.setattr("app.routers.predictions.market_state", lambda exch, now: "open")
    client, fake = predict_client
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        await fake.set("px:quote:005930:KRX", json.dumps(
            {"price": 84300.0, "previous_close": 83000.0, "as_of": stale, "currency": "KRW"}))
        r = await c.get("/stocks/005930:KRX/predict?timeframe=5d", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "SOURCE_DEGRADED"


@pytest.mark.asyncio
async def test_predict_fresh_price_in_market_hours_ok(predict_client, monkeypatch):
    monkeypatch.setattr("app.routers.predictions.market_state", lambda exch, now: "open")
    client, fake = predict_client
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    async with client as c:
        h = {"Authorization": f"Bearer {await _token(c)}"}
        await fake.set("px:quote:005930:KRX", json.dumps(
            {"price": 84300.0, "previous_close": 83000.0, "as_of": fresh, "currency": "KRW"}))
        r = await c.get("/stocks/005930:KRX/predict?timeframe=5d", headers=h)
    assert r.status_code == 200
