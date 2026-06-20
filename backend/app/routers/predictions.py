"""Prediction serving (backend-design ENDPOINTS §6.5). Auth-required. Serves ONLY gate-passed
timeframes (currently 5d); every other timeframe -> 503 MODEL_UNAVAILABLE (disabled-with-note),
never a fake/stale prediction. Every served prediction is inserted synchronously (audit trail).

v1 deferrals (documented): the Redis prediction cache + per-TTL + audit-duplicate-on-cache-hit,
the coverage block, and the 503 SOURCE_DEGRADED price-staleness gate (M6h refinements)."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import ratelimit as rl
from app.auth.deps import get_current_user
from app.cache import redis as cache_redis
from app.cache.redis import make_envelope
from app.config import get_settings
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import predictions as prepo
from app.db.repositories import stocks as srepo
from app.ml.config import TIMEFRAMES
from app.ml.features.builder import build_features
from app.ml.serving.loader import list_servable_timeframes, load_artifact
from app.ml.serving.predict import compute_window_close, run_inference
from app.services import price as price_svc

router = APIRouter()


def _err(status, code, en, ko, rid, details=None):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message_en": en, "message_ko": ko,
        "details": details, "request_id": rid}})


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/stocks/{instrument}/predict")
async def get_predict(instrument: str, request: Request, user=Depends(get_current_user)):
    rid = request.headers.get("x-request-id", "req_local")
    allowed, _, retry = await rl.hit(cache_redis.get_client(), "predict_user", str(user["id"]),
                                     limit=30, window_sec=60)
    if not allowed:
        return rl.rate_limited(rid, retry, 30)
    tf = request.query_params.get("timeframe")
    if tf not in TIMEFRAMES:
        return _err(400, "INVALID_PARAM", "timeframe is required (1h,5h,24h,2d,3d,5d).",
                    "기간(timeframe)을 1h,5h,24h,2d,3d,5d 중에서 선택해 주세요.", rid)
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    settings = get_settings()
    redis = cache_redis.get_client()
    async with connect(settings.sqlite_path) as con:
        ref = await srepo.get_stock(con, symbol, exchange)
        if ref is None:
            return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)

        servable = list_servable_timeframes(settings.model_dir)
        if tf not in servable:
            return _err(503, "MODEL_UNAVAILABLE", "This timeframe is not available yet.",
                        "이 기간 예측은 아직 준비되지 않았어요.", rid,
                        details={"available_timeframes": servable})

        now = datetime.now(timezone.utc)
        as_of = _iso(now)
        cached = await price_svc.read_cached(redis, symbol, exchange)
        entry_price = cached["price"] if cached else None
        window = compute_window_close(as_of, tf)

        artifact = load_artifact(settings.model_dir, tf)
        vector, meta = await build_features(con, redis, ref, tf, as_of)
        rj = run_inference(artifact, vector, meta, stock_ref=ref, timeframe=tf, as_of=as_of,
                           entry_price=entry_price, window_closes_at=window)
        pid = await prepo.insert_prediction(
            con, user_id=user["id"], stock_id=ref.id, timeframe=tf, direction=rj["direction"],
            confidence=rj["confidence"], reasoning_json=rj, model_version=rj["model_version"],
            window_closes_at=window)

    data = {
        "prediction_id": pid, "instrument": f"{symbol}:{exchange}",
        "name_en": ref.company_name or ref.symbol,
        "name_ko": ref.company_name_ko or ref.company_name or ref.symbol,
        "timeframe": tf, "direction": rj["direction"], "confidence": rj["confidence"],
        "evidence": rj["evidence"],
        "evidence_summary_en": " + ".join(e["text_en"] for e in rj["evidence"]),
        "evidence_summary_ko": " + ".join(e["text_ko"] for e in rj["evidence"]),
        "predicted_at": as_of, "window_closes_at": window,
        "entry_price": entry_price, "currency": ref.currency,
        "model_version": rj["model_version"],
        "neutral_rule_applied": rj["neutral_rule_applied"],
        "confidence_capped": rj["confidence_capped"],
        "data_staleness": {"any_stale": rj["data_staleness"]["any_stale"]},
        "high_impact_events": rj["high_impact_events"],
    }
    return JSONResponse(content=make_envelope(
        data, source="model", data_as_of=as_of,
        is_stale=rj["data_staleness"]["any_stale"], cache="miss", request_id=rid))


def _history_item(row, currency):
    rj = json.loads(row["reasoning_json"])
    if row["po_dir"] is None:
        status, outcome = "pending", None
    else:
        status = "correct" if row["po_correct"] == 1 else "incorrect"
        outcome = {"realized_direction": row["po_dir"], "exit_price": row["po_exit"],
                   "move_pct": row["po_pct"], "graded_at": row["po_at"]}
    ev = rj.get("evidence", [])
    return {
        "prediction_id": row["id"], "timeframe": row["timeframe"],
        "direction": row["direction"], "confidence": row["confidence"],
        "evidence_summary_en": " + ".join(e["text_en"] for e in ev),
        "evidence_summary_ko": " + ".join(e["text_ko"] for e in ev),
        "predicted_at": rj.get("predicted_at", row["created_at"]),
        "window_closes_at": row["window_closes_at"],
        "entry_price": rj.get("entry_price"), "currency": currency,
        "model_version": row["model_version"], "status": status, "outcome": outcome,
    }


@router.get("/stocks/{instrument}/history")
async def get_history(instrument: str, request: Request, user=Depends(get_current_user)):
    rid = request.headers.get("x-request-id", "req_local")
    qp = request.query_params
    tf = qp.get("timeframe")
    if tf is not None and tf not in TIMEFRAMES:
        return _err(400, "INVALID_PARAM", "Bad timeframe.", "잘못된 기간이에요.", rid)
    status = qp.get("status")
    if status is not None and status not in ("pending", "correct", "incorrect"):
        return _err(400, "INVALID_PARAM", "Bad status filter.", "잘못된 상태 필터예요.", rid)
    try:
        limit = int(qp.get("limit", 20))
        offset = int(qp.get("offset", 0))
    except ValueError:
        return _err(400, "INVALID_PARAM", "Bad numeric parameter.", "숫자 형식 오류예요.", rid)
    if not (1 <= limit <= 100) or offset < 0:
        return _err(400, "INVALID_PARAM", "limit 1-100, offset >= 0.",
                    "limit는 1-100, offset은 0 이상이어야 해요.", rid)
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    async with connect(get_settings().sqlite_path) as con:
        ref = await srepo.get_stock(con, symbol, exchange)
        if ref is None:
            return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)
        total, rows = await prepo.list_user_history(
            con, user_id=user["id"], stock_id=ref.id, timeframe=tf, status=status,
            limit=limit, offset=offset)

    data = {"instrument": f"{symbol}:{exchange}", "total": total,
            "items": [_history_item(r, ref.currency) for r in rows]}
    return JSONResponse(content=make_envelope(
        data, source="internal", data_as_of=_iso(datetime.now(timezone.utc)),
        is_stale=False, cache="none", request_id=rid))
