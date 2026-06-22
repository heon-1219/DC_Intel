"""In-process response-time + status accumulator (deployment-architecture §8.2). APScheduler runs in
the same process as the API, so the metrics_rollup job reads the same counters the middleware writes —
no Redis round-trip per request. rollup_and_reset() returns the window's stats and clears them."""
import threading
from collections import deque

_LOCK = threading.Lock()
_MAX_SAMPLES = 5000

_state: dict = {
    "count": 0,
    "latency_sum": 0.0,
    "max_ms": 0.0,
    "ok": 0,          # < 400
    "client_err": 0,  # 400–499
    "server_err": 0,  # >= 500
    "rate_limited": 0,  # 429 specifically
    "latencies": deque(maxlen=_MAX_SAMPLES),
}


def record(latency_ms: float, status: int) -> None:
    with _LOCK:
        _state["count"] += 1
        _state["latency_sum"] += latency_ms
        _state["max_ms"] = max(_state["max_ms"], latency_ms)
        _state["latencies"].append(latency_ms)
        if status == 429:
            _state["rate_limited"] += 1
        if status < 400:
            _state["ok"] += 1
        elif status < 500:
            _state["client_err"] += 1
        else:
            _state["server_err"] += 1


def rollup_and_reset() -> dict:
    with _LOCK:
        n = _state["count"]
        lat = sorted(_state["latencies"])
        p95 = lat[min(int(len(lat) * 0.95), len(lat) - 1)] if lat else 0.0
        out = {
            "count": n,
            "avg_ms": round(_state["latency_sum"] / n, 2) if n else 0.0,
            "p95_ms": round(p95, 2),
            "max_ms": round(_state["max_ms"], 2),
            "ok": _state["ok"],
            "client_err": _state["client_err"],
            "server_err": _state["server_err"],
            "rate_limited": _state["rate_limited"],
            "rate_429": round(_state["rate_limited"] / n, 4) if n else 0.0,
        }
        _state.update(
            {"count": 0, "latency_sum": 0.0, "max_ms": 0.0, "ok": 0, "client_err": 0,
             "server_err": 0, "rate_limited": 0})
        _state["latencies"].clear()
        return out
