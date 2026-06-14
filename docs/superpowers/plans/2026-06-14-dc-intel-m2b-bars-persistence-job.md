# M2b — Bar Pipeline, Persistence & `recompute_indicators` Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the M2a pure engine with real OHLCV bars and persist its output — a multi-interval yfinance bar fetcher, the `technical_snapshots` repository, the `indicator_pipeline` orchestrator, the `recompute_indicators` APScheduler job, scheduler/lifespan wiring, and a docker smoke that writes real indicator snapshots end-to-end.

**Architecture:** `YFinanceBarProvider.fetch_bars(ref, interval)` returns a clean UTC-indexed OHLCV DataFrame (regular session only via `prepost=False`, currently-forming bar dropped). The pure `indicators.compute_indicators()` (M2a) turns each frame into the §10.1 payload. `indicator_pipeline.recompute_for_stock()` fetches → computes → upserts per `(stock, interval)`; the `recompute_indicators` job runs it over all active stocks every 5 minutes. Every bar fetch goes through the existing retry + circuit-breaker layer (source `yfinance_bars`).

**Tech Stack:** Python 3.11+, yfinance (lazy-imported), pandas, aiosqlite, redis (fakeredis in tests), APScheduler. Default tests offline (FakeBarProvider + temp SQLite + fakeredis); the real upstream is covered by a `@pytest.mark.live` test + the docker smoke.

---

## Owner standards (binding)
1. **FREE** — yfinance only; no paid bar source.
2. **International + detail-perfect** — payload is the §10.1 contract; UTC timestamps stored ISO-8601.
3. **Local-first** — runs in the localhost docker stack; job is in-process APScheduler.
4. **REAL data always** — the running job fetches live bars. Offline tests use a FakeBarProvider and a synthetic frame **only to exercise the transform/orchestration plumbing** (column renaming, incomplete-bar drop, upsert mapping, job iteration) — never to assert market values; the `@pytest.mark.live` test + docker smoke validate the real bar shape and real computed indicators.

## Spec authorities
- `technical-indicators.md` §3 (interval↔timeframe mapping + §3.1 lookback windows), §8 (regular session only, `prepost=False`), §8.3 (last *completed* bar), §10 (pipeline + §10.1 write contract + §10.2 scheduling/scope).
- `schema.md` / `migrations/001_initial_schema.sql` — `technical_snapshots` columns: scalar `rsi, ema_5, ema_20, ema_50, ema_200, macd, macd_signal, macd_histogram, bollinger_upper, bollinger_lower, bollinger_middle` + `indicators_json` + `UNIQUE(stock_id, bar_interval, timestamp)`, `bar_interval ∈ {'5m','15m','1h','1d'}`.
- `backend-design.md` §9 (retry), `data-sources.md` §9 (circuit breaker).

## Conventions adopted (locked here)
- Intervals: `('5m','15m','1h','1d')`. The three daily timeframes (2d/3d/5d) **share** the single `'1d'` snapshot (§10.1).
- Lookback (calendar days, per §3.1): `5m→14`, `15m→35`, `1h→130`, `1d→1100` (~3y). Fetched via yfinance `start`/`end` (precise; respects yfinance's 5m/15m≤60d, 1h≤730d limits).
- Snapshot `timestamp` = the **last completed bar's** index, as ISO-8601 UTC (`...Z`).
- Bar-fetch failures normalize to `ProviderError` and flow through `with_retry` + the breaker source `"yfinance_bars"` (mirrors `services/price.fetch_and_cache`).
- **Job scope (v1):** compute for **all active stocks** (incl. index pseudo-rows) × all 4 intervals every 5 min. The §10.2 "active symbols" narrowing (open prediction window / recent request) and the after-close-only `1d` schedule are **deferred to M6** (the `predictions` table is empty pre-M6) — mirrors M1's `price_poller` polling the full universe. Logged in the deviation section.
- `compute_indicators` (M2a) is imported, not reimplemented.

## File structure
- Create: `backend/app/db/repositories/technical_snapshots.py` — `upsert_snapshot`, `get_latest_snapshot`.
- Modify: `backend/app/db/repositories/stocks.py` — add `list_active_all`.
- Create: `backend/app/providers/yfinance_bars.py` — `YFinanceBarProvider` + `_normalize`.
- Create: `backend/app/services/indicator_pipeline.py` — `recompute_for_stock`, `_is_first_bar_of_session`, interval constants.
- Create: `backend/app/jobs/indicator_calculator.py` — `recompute_indicators` + `__main__` runner.
- Modify: `backend/app/scheduler.py` — per-job interval map; register `recompute_indicators` (5 min).
- Modify: `backend/app/main.py` — bind `YFinanceBarProvider` + the indicator job in lifespan.
- Modify: `backend/tests/_fakes.py` — add `FakeBarProvider`.
- Modify: `backend/tests/test_scheduler.py` — expect the new job id.
- Create: `backend/tests/test_technical_snapshots_repo.py`, `backend/tests/test_yfinance_bars.py`, `backend/tests/test_indicator_pipeline.py`, `backend/tests/test_indicator_calculator.py`.

---

### Task 1: `technical_snapshots` repository + `list_active_all`

**Files:**
- Create: `backend/app/db/repositories/technical_snapshots.py`
- Modify: `backend/app/db/repositories/stocks.py`
- Test: `backend/tests/test_technical_snapshots_repo.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_technical_snapshots_repo.py`:

```python
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


def _payload():
    return {
        "rsi_14": 73.4, "rsi_state": "overbought",
        "ema_5": 12.51, "ema_20": 11.98, "ema_50": 11.4, "ema_200": 10.85,
        "macd_line": 1.4, "macd_signal": 1.16, "macd_histogram": 0.24,
        "bb_middle": 50.0, "bb_upper": 52.4, "bb_lower": 47.6,
        "bb_percent_b": 1.04, "bb_bandwidth": 0.096, "bb_state": "breakout_up",
        "vol_z20": 1.9, "vol_state": "elevated", "flags": [],
    }


async def _seed_db(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_upsert_then_get_latest_roundtrips(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", _payload())
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert snap["rsi"] == 73.4            # scalar column mapped from rsi_14
    assert snap["macd"] == 1.4            # scalar column mapped from macd_line
    assert snap["bollinger_upper"] == 52.4
    assert snap["timestamp"] == "2026-06-12T06:30:00Z"
    assert snap["indicators"]["rsi_state"] == "overbought"   # parsed indicators_json


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_same_key(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", _payload())
        p2 = _payload(); p2["rsi_14"] = 50.0; p2["rsi_state"] = "neutral"
        await trepo.upsert_snapshot(con, ref.id, "1d", "2026-06-12T06:30:00Z", p2)
        cur = await con.execute(
            "SELECT COUNT(*) AS c FROM technical_snapshots WHERE stock_id=? AND bar_interval='1d'",
            (ref.id,))
        count = (await cur.fetchone())["c"]
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert count == 1            # same (stock, interval, timestamp) -> one row
    assert snap["rsi"] == 50.0   # overwritten


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_empty(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
        assert await trepo.get_latest_snapshot(con, ref.id, "5m") is None


@pytest.mark.asyncio
async def test_list_active_all_includes_indexes(tmp_path):
    db = await _seed_db(tmp_path)
    async with connect(db) as con:
        refs = await srepo.list_active_all(con)
    assert len(refs) == 12   # 7 common/ADR + 5 index pseudo-rows in the seed
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_technical_snapshots_repo.py -v`
Expected: FAIL — `No module named 'app.db.repositories.technical_snapshots'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/db/repositories/technical_snapshots.py`:

```python
import json

# Map §10.1 payload keys -> technical_snapshots scalar columns (schema.md).
_SCALAR_MAP = {
    "rsi": "rsi_14", "ema_5": "ema_5", "ema_20": "ema_20", "ema_50": "ema_50",
    "ema_200": "ema_200", "macd": "macd_line", "macd_signal": "macd_signal",
    "macd_histogram": "macd_histogram", "bollinger_upper": "bb_upper",
    "bollinger_lower": "bb_lower", "bollinger_middle": "bb_middle",
}


async def upsert_snapshot(con, stock_id: int, bar_interval: str, timestamp: str,
                          payload: dict) -> None:
    """Insert (or overwrite on the same (stock, interval, timestamp)) one snapshot:
    scalar columns mapped from the payload + the full payload as indicators_json."""
    cols = ["stock_id", "timestamp", "bar_interval"] + list(_SCALAR_MAP) + ["indicators_json"]
    vals = [stock_id, timestamp, bar_interval]
    vals += [payload.get(src) for src in _SCALAR_MAP.values()]
    vals.append(json.dumps(payload))
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in
                       ("stock_id", "timestamp", "bar_interval"))
    await con.execute(
        f"INSERT INTO technical_snapshots ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(stock_id, bar_interval, timestamp) DO UPDATE SET {updates}",
        vals,
    )
    await con.commit()


async def get_latest_snapshot(con, stock_id: int, bar_interval: str) -> dict | None:
    cur = await con.execute(
        "SELECT * FROM technical_snapshots WHERE stock_id=? AND bar_interval=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (stock_id, bar_interval),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["indicators"] = json.loads(d.pop("indicators_json"))
    return d
```

In `backend/app/db/repositories/stocks.py`, add after `list_active_indexes`:

```python
async def list_active_all(con) -> list[StockRef]:
    cur = await con.execute(f"SELECT {_COLS} FROM stocks WHERE is_active = 1")
    return [_row_to_ref(r) for r in await cur.fetchall()]
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_technical_snapshots_repo.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/repositories/technical_snapshots.py backend/app/db/repositories/stocks.py backend/tests/test_technical_snapshots_repo.py
git commit -m "feat(m2b): technical_snapshots repo (upsert/get_latest) + list_active_all"
```

---

### Task 2: yfinance OHLCV bar provider

**Files:**
- Create: `backend/app/providers/yfinance_bars.py`
- Test: `backend/tests/test_yfinance_bars.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_yfinance_bars.py`:

```python
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers import yfinance_bars as mod
from app.providers.yfinance_bars import YFinanceBarProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


def test_normalize_lowercases_selects_and_utc():
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    idx = pd.to_datetime(["2026-06-10", "2026-06-11"]).tz_localize("UTC")
    raw = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [0, 1],
                        "Close": [1.5, 2.5], "Volume": [10, 20],
                        "Dividends": [0, 0]}, index=idx)
    out = mod._normalize(raw, "1d", now)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert str(out.index.tz) == "UTC"
    assert len(out) == 2   # both daily bars completed (last is 06-11, now is 06-12)


def test_normalize_drops_currently_forming_last_bar():
    now = datetime(2026, 6, 12, 10, 2, tzinfo=timezone.utc)
    # last 5-min bar starts 10:00; it closes at 10:05 > now -> still forming -> dropped.
    idx = pd.to_datetime(["2026-06-12 09:50", "2026-06-12 09:55",
                          "2026-06-12 10:00"]).tz_localize("UTC")
    raw = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
                        "Close": [1, 2, 3], "Volume": [1, 1, 1]}, index=idx)
    out = mod._normalize(raw, "5m", now)
    assert len(out) == 2
    assert out.index[-1] == pd.Timestamp("2026-06-12 09:55", tz="UTC")


def test_normalize_empty_frame_returns_empty():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    out = mod._normalize(pd.DataFrame(), "1d", now)
    assert out.empty


@pytest.mark.asyncio
async def test_fetch_bars_wraps_errors_as_providererror(monkeypatch):
    def boom(ticker, interval, days, now):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(mod.YFinanceBarProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await YFinanceBarProvider().fetch_bars(REF, "1d")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fetch_bars_daily():
    bars = await YFinanceBarProvider().fetch_bars(REF, "1d")
    assert not bars.empty
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert str(bars.index.tz) == "UTC"
    assert len(bars) > 200   # ~3y of daily bars -> EMA200 computable
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_yfinance_bars.py -v -m "not live"`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/providers/yfinance_bars.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.providers.base import StockRef
from app.providers.retry import ProviderError

# Calendar-day lookback per interval (§3.1; respects yfinance 5m/15m<=60d, 1h<=730d).
_DAYS = {"5m": 14, "15m": 35, "1h": 130, "1d": 1100}
INTERVAL_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
_COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame, interval: str, now: datetime) -> pd.DataFrame:
    """Lowercase+select OHLCV, force a UTC index, drop NaN-close rows, and drop the
    currently-forming trailing bar (its interval hasn't closed yet). §8 / §8.3."""
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=_COLS)
    df = df.rename(columns=str.lower)
    df = df[[c for c in _COLS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index, utc=True)   # tz-aware -> UTC; naive -> UTC
    df = df.dropna(subset=["close"])
    if len(df):
        last = df.index[-1].to_pydatetime()
        if last + timedelta(seconds=INTERVAL_SECONDS[interval]) > now:
            df = df.iloc[:-1]
    return df


class YFinanceBarProvider:
    name = "yfinance_bars"

    async def fetch_bars(self, ref: StockRef, interval: str) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        try:
            return await asyncio.to_thread(
                self._fetch, ref.yfinance_ticker, interval, _DAYS[interval], now)
        except Exception as e:  # noqa: BLE001 - normalize everything to retryable
            raise ProviderError(f"yfinance_bars {ref.yfinance_ticker} {interval}: {e}") from e

    @staticmethod
    def _fetch(ticker: str, interval: str, days: int, now: datetime) -> pd.DataFrame:
        import yfinance as yf  # lazy: heavy import; keeps the offline suite fast

        start = (now - timedelta(days=days)).date().isoformat()
        end = (now + timedelta(days=1)).date().isoformat()
        raw = yf.Ticker(ticker).history(
            start=start, end=end, interval=interval, prepost=False, auto_adjust=True)
        return _normalize(raw, interval, now)
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_yfinance_bars.py -v -m "not live"`
Expected: 4 passed (the live test is deselected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/yfinance_bars.py backend/tests/test_yfinance_bars.py
git commit -m "feat(m2b): yfinance OHLCV bar provider (multi-interval, UTC, drops forming bar)"
```

---

### Task 3: indicator pipeline (`recompute_for_stock`)

**Files:**
- Create: `backend/app/services/indicator_pipeline.py`
- Modify: `backend/tests/_fakes.py`
- Test: `backend/tests/test_indicator_pipeline.py`

- [ ] **Step 1: Add `FakeBarProvider` to `tests/_fakes.py`** (append)

```python
class FakeBarProvider:
    def __init__(self, name="yfinance_bars", bars=None, error: Exception | None = None):
        self.name = name
        self._bars = bars        # a pandas DataFrame, or a dict interval -> DataFrame
        self._error = error
        self.calls = 0

    async def fetch_bars(self, ref, interval):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if isinstance(self._bars, dict):
            return self._bars[interval]
        return self._bars
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_indicator_pipeline.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import fakeredis.aioredis
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.providers.breaker import CircuitBreaker
from app.providers.retry import ProviderError
from app.services import indicator_pipeline as pipe
from tests._fakes import FakeBarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)


def _daily_frame(n=260):
    close = pd.Series([100.0 + 0.2 * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close.values, "high": (close + 0.1).values,
                         "low": (close - 0.1).values, "close": close.values,
                         "volume": [100000.0 + i for i in range(n)]}, index=idx)


async def _seed(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG); seed_stocks(db, CSV)
    return db


@pytest.mark.asyncio
async def test_recompute_for_stock_writes_all_intervals(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=_daily_frame())
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, bars, cb, now=NOW)
    assert written == 4   # 5m, 15m, 1h, 1d
    async with connect(db) as con:
        snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
    assert snap["rsi"] == 100.0       # strictly rising frame -> RSI 100
    assert snap["indicators"]["ema_stack_bullish"] is True


@pytest.mark.asyncio
async def test_recompute_skips_empty_frames(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, bars, cb, now=NOW)
    assert written == 0


@pytest.mark.asyncio
async def test_recompute_records_breaker_failure(tmp_path):
    db = await _seed(tmp_path)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    dead = FakeBarProvider(error=ProviderError("down"))
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "005930", "KRX")
    written = await pipe.recompute_for_stock(db, ref, dead, cb, now=NOW)
    assert written == 0
    assert int(await r.get("cb:yfinance_bars:fails")) >= 4   # 4 intervals each failed


def test_is_first_bar_of_session_detects_overnight_gap():
    # last two 5m bars span an overnight gap -> first bar of a new session.
    idx = pd.to_datetime(["2026-06-11 06:25", "2026-06-12 00:00"]).tz_localize("UTC")
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    assert pipe._is_first_bar_of_session(frame, "5m") is True


def test_is_first_bar_of_session_false_for_daily():
    idx = pd.to_datetime(["2026-06-10", "2026-06-11"]).tz_localize("UTC")
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    assert pipe._is_first_bar_of_session(frame, "1d") is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_pipeline.py -v`
Expected: FAIL — `No module named 'app.services.indicator_pipeline'`.

- [ ] **Step 4: Write minimal implementation**

Create `backend/app/services/indicator_pipeline.py`:

```python
from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import technical_snapshots as trepo
from app.providers.retry import ProviderError, with_retry
from app.providers.yfinance_bars import INTERVAL_SECONDS
from app.services.indicators import compute_indicators

INTERVALS = ("5m", "15m", "1h", "1d")
_SOURCE = "yfinance_bars"


def _is_first_bar_of_session(bars, interval: str) -> bool:
    """True if the last bar sits across a gap larger than one interval (a session open).
    Daily bars never count (the vol_z20 session-open guard is an intraday concern)."""
    if interval == "1d" or len(bars) < 2:
        return False
    gap = (bars.index[-1] - bars.index[-2]).total_seconds()
    return gap > 1.5 * INTERVAL_SECONDS[interval]


def _iso(ts) -> str:
    return ts.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def recompute_for_stock(db_path: str, ref, bars_provider, breaker, *,
                              now: datetime, intervals=INTERVALS) -> int:
    """Fetch bars -> compute_indicators -> upsert, per interval. Returns snapshots written.
    Bar fetches go through retry + the circuit breaker (source 'yfinance_bars')."""
    written = 0
    for interval in intervals:
        if await breaker.is_open(_SOURCE):
            continue
        try:
            bars = await with_retry(lambda: bars_provider.fetch_bars(ref, interval))
        except ProviderError:
            await breaker.record_failure(_SOURCE)
            continue
        await breaker.record_success(_SOURCE)
        if bars is None or len(bars) == 0:
            continue
        payload = compute_indicators(
            bars, bar_interval=interval,
            first_bar_of_session=_is_first_bar_of_session(bars, interval))
        ts = _iso(bars.index[-1])
        async with connect(db_path) as con:
            await trepo.upsert_snapshot(con, ref.id, interval, ts, payload)
        written += 1
    return written
```

- [ ] **Step 5: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_pipeline.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/indicator_pipeline.py backend/tests/_fakes.py backend/tests/test_indicator_pipeline.py
git commit -m "feat(m2b): indicator pipeline (recompute_for_stock + session-open detection)"
```

---

### Task 4: `recompute_indicators` job + CLI runner

**Files:**
- Create: `backend/app/jobs/indicator_calculator.py`
- Test: `backend/tests/test_indicator_calculator.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_indicator_calculator.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import fakeredis.aioredis
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.repositories import stocks as srepo
from app.db.repositories import technical_snapshots as trepo
from app.db.seed import seed_stocks
from app.jobs.indicator_calculator import recompute_indicators
from app.providers.breaker import CircuitBreaker
from tests._fakes import FakeBarProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
NOW = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)


def _frame(n=260):
    close = pd.Series([100.0 + 0.2 * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": close.values, "high": (close + 0.1).values,
                         "low": (close - 0.1).values, "close": close.values,
                         "volume": [100000.0 + i for i in range(n)]}, index=idx)


@pytest.mark.asyncio
async def test_recompute_indicators_covers_all_active_stocks(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG); seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    bars = FakeBarProvider(bars=_frame())
    total = await recompute_indicators(db, r, cb, bars_provider=bars, now=NOW)
    assert total == 12 * 4    # 12 active stocks x 4 intervals
    async with connect(db) as con:
        ref = await srepo.get_stock(con, "AAPL", "NASDAQ")
        snap = await trepo.get_latest_snapshot(con, ref.id, "1h")
    assert snap is not None and snap["rsi"] == 100.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_calculator.py -v`
Expected: FAIL — `No module named 'app.jobs.indicator_calculator'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/jobs/indicator_calculator.py`:

```python
from datetime import datetime, timezone

from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.services.indicator_pipeline import recompute_for_stock


async def recompute_indicators(db_path: str, redis, breaker, *, bars_provider,
                               now: datetime | None = None) -> int:
    """Recompute + persist indicator snapshots for every active stock across all
    intervals. Returns total snapshots written. v1 scope = full universe (the §10.2
    'active symbols' narrowing waits for M6's predictions table)."""
    now = now or datetime.now(timezone.utc)
    async with connect(db_path) as con:
        refs = await repo.list_active_all(con)
    total = 0
    for ref in refs:
        total += await recompute_for_stock(db_path, ref, bars_provider, breaker, now=now)
    return total


def _main() -> None:
    import asyncio
    import sys

    from app.cache import redis as cache_redis
    from app.config import get_settings
    from app.core.instrument import parse_instrument
    from app.db.repositories import technical_snapshots as trepo
    from app.providers.breaker import CircuitBreaker
    from app.providers.yfinance_bars import YFinanceBarProvider

    async def _run() -> None:
        s = get_settings()
        r = cache_redis.get_client()
        cb = CircuitBreaker(r)
        bars = YFinanceBarProvider()
        if len(sys.argv) > 1:                      # single-symbol smoke: SYMBOL:EXCHANGE
            sym, exch = parse_instrument(sys.argv[1])
            async with connect(s.sqlite_path) as con:
                ref = await repo.get_stock(con, sym, exch)
            n = await recompute_for_stock(s.sqlite_path, ref, bars, cb,
                                          now=datetime.now(timezone.utc))
            async with connect(s.sqlite_path) as con:
                snap = await trepo.get_latest_snapshot(con, ref.id, "1d")
            print(f"wrote {n} snapshots for {sys.argv[1]}; "
                  f"1d rsi={snap and snap['rsi']} ema_200={snap and snap['ema_200']}")
        else:
            total = await recompute_indicators(s.sqlite_path, r, cb, bars_provider=bars)
            print(f"recompute_indicators wrote {total} snapshots")
        await r.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_calculator.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/indicator_calculator.py backend/tests/test_indicator_calculator.py
git commit -m "feat(m2b): recompute_indicators job (full universe) + CLI smoke runner"
```

---

### Task 5: scheduler + lifespan wiring (5-min cadence)

**Files:**
- Modify: `backend/app/scheduler.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Update the scheduler test** (replace the JOB_IDS expectation)

In `backend/tests/test_scheduler.py`, update the expected job-id set to include the new job and assert its 5-min interval. Replace the assertion block that lists job ids with:

```python
def test_build_scheduler_registers_all_jobs():
    sched = build_scheduler(run=False)
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"poll_prices_krx", "poll_prices_us", "poll_indexes",
                   "heartbeat", "recompute_indicators"}


def test_recompute_indicators_runs_every_5_min():
    from apscheduler.triggers.interval import IntervalTrigger
    sched = build_scheduler(run=False)
    job = sched.get_job("recompute_indicators")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == 300
```

(If `test_scheduler.py` already has a differently-named registration test, replace its body with the first function above and add the second; keep any heartbeat-specific tests unchanged.)

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_scheduler.py -v`
Expected: FAIL — `recompute_indicators` not registered / interval mismatch.

- [ ] **Step 3: Update `scheduler.py`**

Replace the body of `backend/app/scheduler.py` with:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# job id -> interval in minutes. Prices/heartbeat every 1 min; indicators every 5 (§10.2).
JOB_INTERVALS = {
    "poll_prices_krx": 1, "poll_prices_us": 1, "poll_indexes": 1,
    "heartbeat": 1, "recompute_indicators": 5,
}
JOB_IDS = list(JOB_INTERVALS)


async def _noop():
    return None


def build_scheduler(*, run: bool = True, jobs: dict | None = None) -> AsyncIOScheduler:
    """Register the M1+M2 jobs. `jobs` maps id -> coroutine fn (prod callables injected by
    main.py's lifespan); defaults to no-ops so unit tests can introspect registration."""
    jobs = jobs or {jid: _noop for jid in JOB_IDS}
    sched = AsyncIOScheduler(timezone="UTC")
    for jid in JOB_IDS:
        sched.add_job(jobs[jid], IntervalTrigger(minutes=JOB_INTERVALS[jid]), id=jid,
                      max_instances=1, coalesce=True)
    if run:
        sched.start()
    return sched
```

- [ ] **Step 4: Wire the job into `main.py` lifespan**

In `backend/app/main.py`, add imports:

```python
from app.jobs.indicator_calculator import recompute_indicators
from app.providers.yfinance_bars import YFinanceBarProvider
```

After `pk = PykrxProvider()` add:

```python
    bars = YFinanceBarProvider()
```

Add the job callable next to `_hb`:

```python
    async def _ind():
        await recompute_indicators(settings.sqlite_path, redis, breaker, bars_provider=bars)
```

And add it to the `jobs=` dict passed to `build_scheduler`:

```python
    sched = build_scheduler(run=True, jobs={
        "poll_prices_krx": _krx, "poll_prices_us": _us, "poll_indexes": _idx,
        "heartbeat": _hb, "recompute_indicators": _ind})
```

- [ ] **Step 5: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_scheduler.py backend\tests\test_health.py -v`
Expected: all passed (health unaffected; scheduler now registers 5 jobs).

- [ ] **Step 6: Run the full suite**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests -q`
Expected: all M1 + M2a + M2b tests green; 0 failures; live deselected.

- [ ] **Step 7: Commit**

```bash
git add backend/app/scheduler.py backend/app/main.py backend/tests/test_scheduler.py
git commit -m "feat(m2b): register recompute_indicators (5-min) + bind bar provider in lifespan"
```

---

### Task 6: Docker smoke + live check + handoff/memory + push

**Files:**
- Modify: `handoff.md`, `memory/dc-intel-project.md`

- [ ] **Step 1: Optional — run the live bar test once** (validates real upstream)

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_yfinance_bars.py -v -m live`
Expected: `test_live_fetch_bars_daily` PASSES (real ~3y daily bars, >200 rows, UTC). If the network/upstream is unavailable, note it and rely on the docker smoke.

- [ ] **Step 2: Build + bring up the stack**

Run: `docker compose up -d --build`
Then wait for health: `curl http://localhost/healthz` → 200 (sqlite/redis/scheduler true). (Docker Desktop must be running.)

- [ ] **Step 3: Run a single-symbol indicator smoke inside the container**

Run: `docker compose exec backend python -m app.jobs.indicator_calculator 005930:KRX`
Expected: prints e.g. `wrote 4 snapshots for 005930:KRX; 1d rsi=<real 0..100> ema_200=<real price>` — proving real yfinance bars → compute → persist end-to-end. Record the printed values.

- [ ] **Step 4: Confirm the snapshot landed in the DB**

Run: `docker compose exec backend python -c "import asyncio; from app.config import get_settings; from app.db.connection import connect; from app.db.repositories import stocks as s, technical_snapshots as t; \nasync def m():\n async with connect(get_settings().sqlite_path) as c:\n  r=await s.get_stock(c,'005930','KRX'); snap=await t.get_latest_snapshot(c,r.id,'1d'); print(snap['bar_interval'], snap['timestamp'], snap['rsi'], snap['indicators']['rsi_state'])\nasyncio.run(m())"`
Expected: prints `1d <iso-ts> <rsi> <state>` — a real, persisted snapshot.

- [ ] **Step 5: Bring the stack down**

Run: `docker compose down`
Expected: containers removed; the `dbdata` volume persists.

- [ ] **Step 6: Update `handoff.md` and `memory/dc-intel-project.md`**

Mark M2b complete (bar provider + repo + pipeline + job + scheduler wiring + docker smoke), record the smoke values and total test count, and set **🎉 M2 COMPLETE → Next: M3 (economic calendar)** per the roadmap. Note the v1 job-scope deviation (full universe; §10.2 narrowing deferred to M6).

- [ ] **Step 7: Commit + push the milestone**

```bash
git add handoff.md
git commit -m "docs(m2): M2 COMPLETE — indicators end-to-end (M2a engine + M2b pipeline/job + docker smoke)"
git push origin main
```

---

## Self-Review (run after writing; fixed inline)

**Spec coverage vs `technical-indicators.md` §3/§8/§10:**
- §3 interval↔timeframe mapping + §3.1 lookback windows → Task 2 (`_DAYS`) + Task 3 (`INTERVALS`). ✓
- §8 regular-session-only (`prepost=False`) + §8.3 last completed bar → Task 2 (`_normalize` drops the forming bar; `prepost=False`). ✓
- §10 pipeline (fetch→compute→persist) → Tasks 2–4. ✓
- §10.1 write contract (scalar cols mapped + `indicators_json`, `UNIQUE(stock,interval,timestamp)` upsert) → Task 1. ✓
- §10.2 cadence (5-min) → Task 5; **scope/after-close-`1d` narrowing deferred to M6** (documented deviation). ✓
- Retry + circuit breaker on every external call → Task 3 (`with_retry` + breaker source `yfinance_bars`). ✓

**Deviations logged (intentional v1):** job computes the full active universe every 5 min for all 4 intervals (the §10.2 "active symbols" + after-close-only-`1d` optimizations wait for M6's `predictions` data); `auto_adjust=True` for split-clean daily history.

**Placeholder scan:** none — every step has complete code/commands.

**Type consistency:** `recompute_for_stock(db_path, ref, bars_provider, breaker, *, now, intervals)` and `recompute_indicators(db_path, redis, breaker, *, bars_provider, now=None)` are consistent across Tasks 3–5 and main.py; `upsert_snapshot(con, stock_id, bar_interval, timestamp, payload)` / `get_latest_snapshot(con, stock_id, bar_interval)` consistent across Tasks 1, 3, 4, 6; `YFinanceBarProvider.fetch_bars(ref, interval)` / `_normalize(df, interval, now)` / `INTERVAL_SECONDS` consistent across Tasks 2, 3; `list_active_all(con)` consistent across Tasks 1, 4. `FakeBarProvider` matches the `fetch_bars` signature used by the pipeline.
```
