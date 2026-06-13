# M1a — Live Single-Listing Prices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans` (inline) or `superpowers:subagent-driven-development`. Steps use `- [ ]`. This is slice **M1a** of milestone M1 in `2026-06-13-dc-intel-phase4-roadmap.md`. Builds on M0 (done). M1b (cross-market + FX) follows.

**Goal:** Serve **real** live prices at `GET /stocks/{symbol}:{exchange}/price` — fetched from Yahoo Finance (yfinance) with Finnhub (US) / pykrx (KRX) fallbacks, cached in Redis by a 1-minute `price_poller` background job, with honest `is_stale`/`market_state`.

**Architecture:** Provider abstraction (`Provider` protocol) behind a retry helper + Redis circuit breaker. A region-aware provider chain. The `price_poller` APScheduler job fetches every active stock and writes `px:quote:{symbol}:{exchange}` to Redis with `as_of`. The `/price` handler only reads cache (never fetches inline), computing `change`/`market_state`/`is_stale` per `backend-design.md` §6.4.

**Tech stack (new this slice):** yfinance, pykrx, tzdata (zoneinfo on Windows), APScheduler; respx (dev) for HTTP cassette tests. Existing: FastAPI, aiosqlite, redis, httpx.

**Conventions:** TDD; offline-deterministic default suite (fakes + fakeredis); real upstreams covered by `@pytest.mark.live` tests excluded from the default run. **Real data always:** the app fetches live; tests use fakes/recorded fixtures, never fabricated market values presented as real.

**Environment:** uv venv at `backend/.venv` (see M0 plan). Run tests: `backend\.venv\Scripts\python.exe -m pytest backend\tests` (default skips `live`). New deps installed in Task 0.

---

## File structure built in M1a

- `backend/app/providers/base.py` — `StockRef`, `PriceQuote`, `Provider` protocol
- `backend/app/providers/retry.py` — `ProviderError`, `with_retry`
- `backend/app/providers/breaker.py` — `CircuitBreaker` (Redis `cb:*`)
- `backend/app/providers/yfinance_provider.py` — primary adapter
- `backend/app/providers/finnhub_provider.py` — US fallback (httpx)
- `backend/app/providers/pykrx_provider.py` — KRX fallback
- `backend/app/market/hours.py` — `market_state(exchange, now_utc)`
- `backend/app/db/repositories/stocks.py` — `get_stock`, `list_active_by_region`
- `backend/app/core/instrument.py` — `parse_instrument` (`{symbol}:{exchange}` grammar)
- `backend/app/services/price.py` — provider chain, `fetch_and_cache`, `read_cached`, `is_stale`
- `backend/app/jobs/price_poller.py` — `poll_prices` + region entrypoints
- `backend/app/scheduler.py` — APScheduler setup, registered in `main.py` lifespan
- `backend/app/routers/stocks.py` — `GET /stocks/{instrument}/price`
- `backend/tests/` — `_fakes.py` (FakeProvider) + one test module per unit; `pytest.ini` marker `live`

---

### Task 0: M1a dependencies + `live` marker

**Files:** Modify `backend/pyproject.toml`

- [ ] **Step 1: Add runtime + dev deps and the `live` marker**

In `backend/pyproject.toml`, extend `[project] dependencies` with:
```toml
    "yfinance>=0.2.40",
    "pykrx>=1.0.45",
    "tzdata>=2024.1",
    "apscheduler>=3.10",
```
Extend `[project.optional-dependencies] dev` with `"respx>=0.21"`. Add under `[tool.pytest.ini_options]`:
```toml
markers = ["live: hits real external APIs; excluded from the default run"]
addopts = "-m 'not live'"
```

- [ ] **Step 2: Install and confirm the suite still green**

Run:
```
uv pip install -p backend\.venv\Scripts\python.exe -e "./backend[dev]"
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```
Expected: install OK; **18 passed** (M0 suite unaffected; `-m 'not live'` now active).

- [ ] **Step 3: Commit** — `git add backend/pyproject.toml && git commit -m "build: add M1a deps (yfinance/pykrx/tzdata/apscheduler/respx) + live marker"`

---

### Task 1: Domain types + Provider protocol + FakeProvider

**Files:** Create `backend/app/providers/__init__.py`, `backend/app/providers/base.py`, `backend/tests/_fakes.py`, `backend/tests/test_providers_base.py`

- [ ] **Step 1: Failing test**

`backend/tests/test_providers_base.py`:
```python
from datetime import datetime, timezone
from app.providers.base import PriceQuote, StockRef


def test_pricequote_and_stockref_construct():
    ref = StockRef(id=1, symbol="005930", exchange="KRX", region="KR",
                   currency="KRW", yfinance_ticker="005930.KS", finnhub_ticker=None)
    q = PriceQuote(price=84300.0, previous_close=83600.0, volume=11250300,
                   day_high=84600.0, day_low=83400.0, as_of=datetime(2026, 6, 12, tzinfo=timezone.utc))
    assert ref.yfinance_ticker == "005930.KS"
    assert q.price == 84300.0 and q.as_of.tzinfo is timezone.utc
```

- [ ] **Step 2: Run → FAIL** (`No module named 'app.providers'`).

- [ ] **Step 3: Implement**

`backend/app/providers/__init__.py`: (empty)

`backend/app/providers/base.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StockRef:
    id: int
    symbol: str
    exchange: str
    region: str
    currency: str
    yfinance_ticker: str
    finnhub_ticker: str | None


@dataclass(frozen=True)
class PriceQuote:
    price: float
    previous_close: float | None
    volume: int | None
    day_high: float | None
    day_low: float | None
    as_of: datetime  # timezone-aware UTC


class Provider(Protocol):
    name: str
    async def fetch_quote(self, ref: StockRef) -> PriceQuote: ...
```

`backend/tests/_fakes.py`:
```python
from app.providers.base import PriceQuote, StockRef


class FakeProvider:
    def __init__(self, name: str, quote: PriceQuote | None = None, error: Exception | None = None):
        self.name = name
        self._quote = quote
        self._error = error
        self.calls = 0

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._quote is not None
        return self._quote
```

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: provider domain types (StockRef, PriceQuote, Provider)`.

---

### Task 2: Retry helper

**Files:** Create `backend/app/providers/retry.py`, `backend/tests/test_retry.py`

- [ ] **Step 1: Failing test** (deterministic: injected `sleep` recorder + `rng` returning 1.0)

`backend/tests/test_retry.py`:
```python
import pytest
from app.providers.retry import with_retry, ProviderError


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    slept = []
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("flaky")
        return "ok"

    async def fake_sleep(d):
        slept.append(d)

    out = await with_retry(fn, sleep=fake_sleep, rng=lambda: 1.0)
    assert out == "ok"
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]  # base*2^0, base*2^1 (full jitter rng=1.0)


@pytest.mark.asyncio
async def test_exhausts_and_raises():
    async def fn():
        raise ProviderError("always")
    with pytest.raises(ProviderError):
        await with_retry(fn, attempts=2, sleep=lambda d: _noop(), rng=lambda: 0.0)


@pytest.mark.asyncio
async def test_non_retryable_propagates_immediately():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        raise ValueError("boom")
    with pytest.raises(ValueError):
        await with_retry(fn, retry_on=(ProviderError,), sleep=lambda d: _noop())
    assert calls["n"] == 1


async def _noop():
    return None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/providers/retry.py`:
```python
import asyncio
import random
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class ProviderError(Exception):
    """Retryable upstream failure (timeout / 5xx / 429)."""


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base: float = 0.5,
    cap: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (ProviderError, TimeoutError),
    sleep: Callable[[float], Awaitable] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Exponential backoff with full jitter. Retries only `retry_on`; re-raises the last."""
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except retry_on as e:  # type: ignore[misc]
            last = e
            if i == attempts - 1:
                break
            delay = min(cap, base * (2 ** i)) * rng()
            await sleep(delay)
    assert last is not None
    raise last
```

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: provider retry helper (exp backoff, full jitter)`.

---

### Task 3: Circuit breaker (Redis)

**Files:** Create `backend/app/providers/breaker.py`, `backend/tests/test_breaker.py`

- [ ] **Step 1: Failing test** (fakeredis)

`backend/tests/test_breaker.py`:
```python
import fakeredis.aioredis
import pytest
from app.providers.breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_opens_after_threshold_and_clears_on_success():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r, threshold=3, cooldown_s=60)
    assert await cb.is_open("yfinance") is False
    for _ in range(3):
        await cb.record_failure("yfinance")
    assert await cb.is_open("yfinance") is True
    await cb.record_success("yfinance")
    assert await cb.is_open("yfinance") is False
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/providers/breaker.py`:
```python
class CircuitBreaker:
    """Minimal Redis circuit breaker. Opens after `threshold` failures within the
    cooldown window; auto half-opens when the open key expires (cooldown_s)."""

    def __init__(self, redis, *, threshold: int = 5, cooldown_s: int = 60):
        self.redis = redis
        self.threshold = threshold
        self.cooldown_s = cooldown_s

    async def is_open(self, source: str) -> bool:
        return bool(await self.redis.exists(f"cb:{source}:open"))

    async def record_failure(self, source: str) -> None:
        fails = await self.redis.incr(f"cb:{source}:fails")
        await self.redis.expire(f"cb:{source}:fails", self.cooldown_s)
        if fails >= self.threshold:
            await self.redis.set(f"cb:{source}:open", "1", ex=self.cooldown_s)

    async def record_success(self, source: str) -> None:
        await self.redis.delete(f"cb:{source}:fails", f"cb:{source}:open")
```

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: redis circuit breaker for providers`.

---

### Task 4: Market-hours helper

**Files:** Create `backend/app/market/__init__.py`, `backend/app/market/hours.py`, `backend/tests/test_hours.py`

- [ ] **Step 1: Failing test** (inject `now_utc`)

`backend/tests/test_hours.py`:
```python
from datetime import datetime, timezone
from app.market.hours import market_state


def _utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_krx_open_friday_midsession():
    # 2026-06-12 is a Friday. 05:00 UTC = 14:00 KST -> open.
    assert market_state("KRX", _utc(2026, 6, 12, 5, 0)) == "open"


def test_krx_closed_weekend():
    # 2026-06-13 is a Saturday.
    assert market_state("KRX", _utc(2026, 6, 13, 5, 0)) == "closed"


def test_nyse_states():
    # 2026-06-12 Friday. ET = UTC-4 (EDT in June).
    assert market_state("NYSE", _utc(2026, 6, 12, 14, 0)) == "open"   # 10:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 12, 0)) == "pre"    # 08:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 21, 0)) == "post"   # 17:00 ET
    assert market_state("NYSE", _utc(2026, 6, 12, 2, 0)) == "closed"  # 22:00 ET prev


def test_unknown_exchange_closed():
    assert market_state("OTC", _utc(2026, 6, 12, 14, 0)) == "closed"
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/market/__init__.py` (empty) and `backend/app/market/hours.py`:
```python
from datetime import datetime, time
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_ET = ZoneInfo("America/New_York")
_US = {"NASDAQ", "NYSE", "AMEX"}


def market_state(exchange: str, now_utc: datetime) -> str:
    """One of open|closed|pre|post. v1: regular weekly sessions only (no exchange
    holidays — documented limitation, data-sources.md). pre/post are US-only."""
    if exchange == "KRX":
        local = now_utc.astimezone(_KST)
        if local.weekday() >= 5:
            return "closed"
        return "open" if time(9, 0) <= local.time() <= time(15, 30) else "closed"
    if exchange in _US:
        local = now_utc.astimezone(_ET)
        if local.weekday() >= 5:
            return "closed"
        t = local.time()
        if time(9, 30) <= t <= time(16, 0):
            return "open"
        if time(4, 0) <= t < time(9, 30):
            return "pre"
        if time(16, 0) < t <= time(20, 0):
            return "post"
        return "closed"
    return "closed"  # INDEX/OTC: no live-session concept in v1
```

- [ ] **Step 4: Run → PASS** (depends on `tzdata` from Task 0).  **Step 5: Commit** `feat: exchange market-hours / market_state helper`.

---

### Task 5: yfinance adapter (primary)

**Files:** Create `backend/app/providers/yfinance_provider.py`, `backend/tests/test_yfinance_provider.py`

- [ ] **Step 1: Failing test** — offline: error-wrapping; plus a `live` happy-path.

`backend/tests/test_yfinance_provider.py`:
```python
import pytest
from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers.yfinance_provider import YFinanceProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


@pytest.mark.asyncio
async def test_wraps_upstream_errors_as_providererror(monkeypatch):
    import app.providers.yfinance_provider as mod

    def boom(ticker):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(mod.YFinanceProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await YFinanceProvider().fetch_quote(REF)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fetch_samsung():
    q = await YFinanceProvider().fetch_quote(REF)
    assert q.price > 0 and q.as_of is not None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/providers/yfinance_provider.py`:
```python
import asyncio
from datetime import datetime, timezone

import yfinance as yf

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError


def _f(v):
    return None if v is None else float(v)


def _i(v):
    return None if v is None else int(v)


class YFinanceProvider:
    name = "yfinance"

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        try:
            return await asyncio.to_thread(self._fetch, ref.yfinance_ticker)
        except Exception as e:  # noqa: BLE001 - normalize everything to retryable
            raise ProviderError(f"yfinance {ref.yfinance_ticker}: {e}") from e

    @staticmethod
    def _fetch(ticker: str) -> PriceQuote:
        fi = yf.Ticker(ticker).fast_info
        # fast_info supports mapping access; key names finalized against the installed
        # yfinance version by the live test (NOTE in handoff if they differ).
        price = fi["last_price"]
        if price is None:
            raise ValueError("no last_price")
        return PriceQuote(
            price=float(price),
            previous_close=_f(fi.get("previous_close")),
            volume=_i(fi.get("last_volume")),
            day_high=_f(fi.get("day_high")),
            day_low=_f(fi.get("day_low")),
            as_of=datetime.now(timezone.utc),
        )
```

- [ ] **Step 4: Run → PASS** (the `live` test is skipped by default).  Run the live test once manually to finalize `fast_info` keys: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_yfinance_provider.py -m live -q` — if a KeyError shows different names (e.g. `lastPrice`), adjust `_fetch` and note it.  **Step 5: Commit** `feat: yfinance price adapter (primary)`.

---

### Task 6: Fallback adapters — Finnhub (US) + pykrx (KRX)

**Files:** Create `backend/app/providers/finnhub_provider.py`, `backend/app/providers/pykrx_provider.py`, `backend/tests/test_finnhub_provider.py`, `backend/tests/test_pykrx_provider.py`

- [ ] **Step 1: Failing tests** — Finnhub via respx (recorded shape); pykrx error-wrap + `live`.

`backend/tests/test_finnhub_provider.py`:
```python
import httpx
import pytest
import respx
from app.providers.base import StockRef
from app.providers.finnhub_provider import FinnhubProvider

REF = StockRef(5, "AAPL", "NASDAQ", "US", "USD", "AAPL", "AAPL")


@pytest.mark.asyncio
@respx.mock
async def test_finnhub_quote_maps_fields():
    # Real Finnhub /quote shape: c=current, pc=prev close, h=high, l=low, t=epoch.
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 201.5, "pc": 199.0, "h": 203.0, "l": 198.4, "t": 1749700000})
    )
    q = await FinnhubProvider(api_key="k").fetch_quote(REF)
    assert q.price == 201.5 and q.previous_close == 199.0 and q.day_high == 203.0
```

`backend/tests/test_pykrx_provider.py`:
```python
import pytest
from app.providers.base import StockRef
from app.providers.retry import ProviderError
from app.providers.pykrx_provider import PykrxProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)


@pytest.mark.asyncio
async def test_pykrx_wraps_errors(monkeypatch):
    import app.providers.pykrx_provider as mod

    def boom(symbol):
        raise RuntimeError("krx down")
    monkeypatch.setattr(mod.PykrxProvider, "_fetch", staticmethod(boom))
    with pytest.raises(ProviderError):
        await PykrxProvider().fetch_quote(REF)


@pytest.mark.live
@pytest.mark.asyncio
async def test_pykrx_live():
    q = await PykrxProvider().fetch_quote(REF)
    assert q.price > 0
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement.**

`backend/app/providers/finnhub_provider.py`:
```python
from datetime import datetime, timezone

import httpx

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError

_BASE = "https://finnhub.io/api/v1/quote"


class FinnhubProvider:
    name = "finnhub"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        symbol = ref.finnhub_ticker or ref.symbol
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(_BASE, params={"symbol": symbol, "token": self.api_key})
            if resp.status_code in (429,) or resp.status_code >= 500:
                raise ProviderError(f"finnhub http {resp.status_code}")
            resp.raise_for_status()
            d = resp.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"finnhub {symbol}: {e}") from e
        if not d.get("c"):
            raise ProviderError(f"finnhub {symbol}: empty quote")
        ts = d.get("t")
        return PriceQuote(
            price=float(d["c"]),
            previous_close=float(d["pc"]) if d.get("pc") else None,
            volume=None,  # /quote has no volume; left null in v1
            day_high=float(d["h"]) if d.get("h") else None,
            day_low=float(d["l"]) if d.get("l") else None,
            as_of=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc),
        )
```

`backend/app/providers/pykrx_provider.py`:
```python
import asyncio
from datetime import datetime, timezone

from pykrx import stock as krx

from app.providers.base import PriceQuote, StockRef
from app.providers.retry import ProviderError


class PykrxProvider:
    name = "pykrx"

    async def fetch_quote(self, ref: StockRef) -> PriceQuote:
        try:
            return await asyncio.to_thread(self._fetch, ref.symbol)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"pykrx {ref.symbol}: {e}") from e

    @staticmethod
    def _fetch(symbol: str) -> PriceQuote:
        today = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        df = krx.get_market_ohlcv(today, today, symbol)  # columns: 시가/고가/저가/종가/거래량
        if df is None or df.empty:
            raise ValueError("no ohlcv row")
        row = df.iloc[-1]
        return PriceQuote(
            price=float(row["종가"]),
            previous_close=None,  # single-day OHLCV has no prior close; filled by service from cache later
            volume=int(row["거래량"]),
            day_high=float(row["고가"]),
            day_low=float(row["저가"]),
            as_of=datetime.now(timezone.utc),
        )
```

- [ ] **Step 4: Run → PASS** (finnhub respx test green; pykrx error-wrap green; `live` skipped).  **Step 5: Commit** `feat: finnhub (US) and pykrx (KRX) fallback price adapters`.

---

### Task 7: Stocks repository + instrument parser

**Files:** Create `backend/app/db/repositories/__init__.py`, `backend/app/db/repositories/stocks.py`, `backend/app/core/__init__.py`, `backend/app/core/instrument.py`, `backend/tests/test_instrument.py`, `backend/tests/test_stocks_repo.py`

- [ ] **Step 1: Failing tests**

`backend/tests/test_instrument.py`:
```python
import pytest
from app.core.instrument import parse_instrument, InvalidInstrument


def test_parses_and_uppercases():
    assert parse_instrument("aapl:nasdaq") == ("AAPL", "NASDAQ")
    assert parse_instrument("005930:KRX") == ("005930", "KRX")


@pytest.mark.parametrize("bad", ["AAPL", "AAPL:FOO", ":KRX", "AAPL:", "A B:KRX"])
def test_rejects_bad(bad):
    with pytest.raises(InvalidInstrument):
        parse_instrument(bad)
```

`backend/tests/test_stocks_repo.py`:
```python
import pytest
from pathlib import Path
from app.db.connection import connect
from app.db.migrate import migrate
from app.db.seed import seed_stocks
from app.db.repositories import stocks as repo

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "t.db")
    migrate(p, MIG)
    seed_stocks(p, CSV)
    return p


@pytest.mark.asyncio
async def test_get_stock_found_and_missing(db):
    async with connect(db) as con:
        ref = await repo.get_stock(con, "005930", "KRX")
        assert ref is not None and ref.yfinance_ticker == "005930.KS" and ref.region == "KR"
        assert await repo.get_stock(con, "ZZZZ", "KRX") is None


@pytest.mark.asyncio
async def test_list_active_by_region(db):
    async with connect(db) as con:
        kr = await repo.list_active_by_region(con, "KR")
        assert any(r.symbol == "005930" for r in kr)
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement.**

`backend/app/core/__init__.py` (empty). `backend/app/core/instrument.py`:
```python
import re

_VALID_EXCHANGES = {"KRX", "NASDAQ", "NYSE", "AMEX", "OTC"}  # INDEX not addressable (schema.md §1.5)
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


class InvalidInstrument(ValueError):
    pass


def parse_instrument(raw: str) -> tuple[str, str]:
    """'{symbol}:{exchange}' -> (SYMBOL, EXCHANGE), uppercased. Raises InvalidInstrument."""
    if raw.count(":") != 1:
        raise InvalidInstrument(raw)
    symbol, exchange = raw.split(":", 1)
    symbol, exchange = symbol.strip().upper(), exchange.strip().upper()
    if not _SYMBOL_RE.match(symbol) or exchange not in _VALID_EXCHANGES:
        raise InvalidInstrument(raw)
    return symbol, exchange
```

`backend/app/db/repositories/__init__.py` (empty). `backend/app/db/repositories/stocks.py`:
```python
from app.providers.base import StockRef

_COLS = "id, symbol, exchange, region, currency, yfinance_ticker, finnhub_ticker"


def _row_to_ref(row) -> StockRef:
    return StockRef(
        id=row["id"], symbol=row["symbol"], exchange=row["exchange"], region=row["region"],
        currency=row["currency"], yfinance_ticker=row["yfinance_ticker"],
        finnhub_ticker=row["finnhub_ticker"],
    )


async def get_stock(con, symbol: str, exchange: str) -> StockRef | None:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE symbol = ? AND exchange = ? AND is_active = 1",
        (symbol, exchange),
    )
    row = await cur.fetchone()
    return _row_to_ref(row) if row else None


async def list_active_by_region(con, region: str) -> list[StockRef]:
    cur = await con.execute(
        f"SELECT {_COLS} FROM stocks WHERE region = ? AND is_active = 1 AND security_type != 'index'",
        (region,),
    )
    return [_row_to_ref(r) for r in await cur.fetchall()]
```

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: stocks repository + {symbol}:{exchange} instrument parser`.

---

### Task 8: Price service (chain, cache, staleness)

**Files:** Create `backend/app/services/__init__.py`, `backend/app/services/price.py`, `backend/tests/test_price_service.py`

- [ ] **Step 1: Failing test** (FakeProvider chain + fakeredis)

`backend/tests/test_price_service.py`:
```python
from datetime import datetime, timezone, timedelta

import fakeredis.aioredis
import pytest

from app.providers.base import PriceQuote, StockRef
from app.providers.breaker import CircuitBreaker
from app.providers.retry import ProviderError
from app.services import price as svc
from tests._fakes import FakeProvider

REF = StockRef(1, "005930", "KRX", "KR", "KRW", "005930.KS", None)
Q = PriceQuote(84300.0, 83600.0, 11250300, 84600.0, 83400.0, datetime(2026, 6, 12, 5, 30, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_fetch_and_cache_falls_through_chain_and_writes():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    p1 = FakeProvider("yfinance", error=ProviderError("down"))
    p2 = FakeProvider("pykrx", quote=Q)
    out = await svc.fetch_and_cache(REF, [p1, p2], r, cb)
    assert out is not None and out.price == 84300.0
    cached = await svc.read_cached(r, "005930", "KRX")
    assert cached["price"] == 84300.0 and cached["source"] == "pykrx"


@pytest.mark.asyncio
async def test_open_breaker_skips_provider():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r, threshold=1)
    await cb.record_failure("yfinance")  # opens
    p1 = FakeProvider("yfinance", quote=Q)
    p2 = FakeProvider("pykrx", quote=Q)
    await svc.fetch_and_cache(REF, [p1, p2], r, cb)
    assert p1.calls == 0 and p2.calls == 1  # yfinance skipped (open), pykrx used


def test_is_stale_rules():
    now = datetime(2026, 6, 12, 5, 40, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=3)
    old = now - timedelta(minutes=10)
    assert svc.is_stale(old, "open", now) is True
    assert svc.is_stale(fresh, "open", now) is False
    assert svc.is_stale(old, "closed", now) is False  # never stale when closed
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/services/__init__.py` (empty) and `backend/app/services/price.py`:
```python
import json
from datetime import datetime, timezone

from app.providers.base import PriceQuote, StockRef

STALE_AFTER_S = 5 * 60


def _key(symbol: str, exchange: str) -> str:
    return f"px:quote:{symbol}:{exchange}"


def provider_chain(region: str, *, yfinance, finnhub, pykrx) -> list:
    """Region-aware order: KR -> yfinance, pykrx; US -> yfinance, finnhub; else yfinance."""
    if region == "KR":
        return [yfinance, pykrx]
    if region == "US":
        return [yfinance, finnhub]
    return [yfinance]


async def fetch_and_cache(ref: StockRef, providers: list, redis, breaker) -> PriceQuote | None:
    for p in providers:
        if await breaker.is_open(p.name):
            continue
        try:
            q = await p.fetch_quote(ref)
        except Exception:  # noqa: BLE001 - provider already normalizes; treat as failure
            await breaker.record_failure(p.name)
            continue
        await breaker.record_success(p.name)
        await redis.set(_key(ref.symbol, ref.exchange), json.dumps({
            "price": q.price, "previous_close": q.previous_close, "volume": q.volume,
            "day_high": q.day_high, "day_low": q.day_low, "currency": ref.currency,
            "as_of": q.as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": p.name,
        }))
        return q
    return None


async def read_cached(redis, symbol: str, exchange: str) -> dict | None:
    raw = await redis.get(_key(symbol, exchange))
    return json.loads(raw) if raw else None


def is_stale(as_of: datetime, market_state: str, now: datetime) -> bool:
    if market_state != "open":
        return False
    return (now - as_of).total_seconds() > STALE_AFTER_S
```

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: price service (provider chain, cache write, staleness rule)`.

---

### Task 9: price_poller job

**Files:** Create `backend/app/jobs/__init__.py`, `backend/app/jobs/price_poller.py`, `backend/tests/test_price_poller.py`

- [ ] **Step 1: Failing test** (seeded temp DB + FakeProvider + fakeredis)

`backend/tests/test_price_poller.py`:
```python
from datetime import datetime, timezone
from pathlib import Path

import fakeredis.aioredis
import pytest

from app.db.migrate import migrate
from app.db.seed import seed_stocks
from app.providers.base import PriceQuote
from app.providers.breaker import CircuitBreaker
from app.jobs.price_poller import poll_region
from app.services import price as svc
from tests._fakes import FakeProvider

MIG = str(Path(__file__).resolve().parents[1] / "migrations")
CSV = str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv")
Q = PriceQuote(100.0, 99.0, 10, 101.0, 98.0, datetime(2026, 6, 12, 5, 30, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_poll_region_caches_each_kr_stock(tmp_path):
    db = str(tmp_path / "t.db")
    migrate(db, MIG)
    seed_stocks(db, CSV)
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cb = CircuitBreaker(r)
    fake = FakeProvider("yfinance", quote=Q)
    n = await poll_region(db, "KR", r, cb, yfinance=fake, finnhub=fake, pykrx=fake)
    assert n == 4  # 4 KR common stocks in the seed (indexes excluded)
    assert (await svc.read_cached(r, "005930", "KRX"))["price"] == 100.0
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/jobs/__init__.py` (empty) and `backend/app/jobs/price_poller.py`:
```python
from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.services import price as svc


async def poll_region(db_path: str, region: str, redis, breaker, *, yfinance, finnhub, pykrx) -> int:
    """Fetch + cache every active (non-index) stock in `region`. Returns count cached."""
    cached = 0
    async with connect(db_path) as con:
        refs = await repo.list_active_by_region(con, region)
    for ref in refs:
        chain = svc.provider_chain(ref.region, yfinance=yfinance, finnhub=finnhub, pykrx=pykrx)
        if await svc.fetch_and_cache(ref, chain, redis, breaker) is not None:
            cached += 1
    return cached
```
(NOTE: per-stock fetch in v1; the `data-sources.md` batched-per-exchange optimization is a documented later refinement.)

- [ ] **Step 4: Run → PASS.**  **Step 5: Commit** `feat: price_poller region job`.

---

### Task 10: `GET /stocks/{i}/price` endpoint

**Files:** Create `backend/app/routers/stocks.py`; Modify `backend/app/main.py`; Create `backend/tests/test_price_endpoint.py`

- [ ] **Step 1: Failing test** (app_client + seeded DB + pre-populated fake cache)

`backend/tests/test_price_endpoint.py`:
```python
import json

import pytest


async def _seed_quote(app_client_module):
    # helper inlined per test below
    ...


@pytest.mark.asyncio
async def test_price_returns_cached_quote(app_client, monkeypatch):
    # Pre-populate the fake Redis used by the app with a quote for 005930:KRX.
    import app.cache.redis as cache_redis
    client_obj = cache_redis.get_client()  # the fixture's fake
    await client_obj.set("px:quote:005930:KRX", json.dumps({
        "price": 84300.0, "previous_close": 83600.0, "volume": 11250300,
        "day_high": 84600.0, "day_low": 83400.0, "currency": "KRW",
        "as_of": "2026-06-12T05:30:45Z", "source": "yfinance"}))
    async with app_client as c:
        r = await c.get("/stocks/005930:KRX/price")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["instrument"] == "005930:KRX" and d["price"] == 84300.0
    assert d["change"] == 700.0 and round(d["change_pct"], 2) == 0.84
    assert r.json()["meta"]["source"] == "yfinance"


@pytest.mark.asyncio
async def test_price_404_when_unknown_symbol(app_client):
    async with app_client as c:
        r = await c.get("/stocks/ZZZZ:KRX/price")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_price_400_on_bad_instrument(app_client):
    async with app_client as c:
        r = await c.get("/stocks/AAPL:FOO/price")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_price_404_when_known_symbol_no_quote_yet(app_client):
    async with app_client as c:
        r = await c.get("/stocks/000660:KRX/price")  # seeded but no cached quote
    assert r.status_code == 404
```

**conftest note:** the seed must run in the `app_client` fixture so symbols resolve. Add `from app.db.seed import seed_stocks` and after `migrate(...)` call `seed_stocks(get_settings().sqlite_path, str(Path(__file__).resolve().parents[2] / "config" / "seed_stocks.csv"))`. (Update `backend/tests/conftest.py` accordingly in this task's Step 3.)

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement.** Update `conftest.py` to seed (above). `backend/app/routers/stocks.py`:
```python
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.cache import redis as cache_redis
from app.config import get_settings
from app.core.instrument import InvalidInstrument, parse_instrument
from app.db.connection import connect
from app.db.repositories import stocks as repo
from app.market.hours import market_state
from app.services import price as svc

router = APIRouter()


def _err(status, code, en, ko, request_id):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message_en": en, "message_ko": ko, "request_id": request_id}})


@router.get("/stocks/{instrument}/price")
async def get_price(instrument: str, request: Request):
    rid = request.headers.get("x-request-id", "req_local")
    try:
        symbol, exchange = parse_instrument(instrument)
    except InvalidInstrument:
        return _err(400, "INVALID_PARAM", "Malformed instrument.", "잘못된 종목 형식이에요.", rid)

    settings = get_settings()
    async with connect(settings.sqlite_path) as con:
        ref = await repo.get_stock(con, symbol, exchange)
    if ref is None:
        return _err(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.", rid)

    cached = await svc.read_cached(cache_redis.get_client(), symbol, exchange)
    if cached is None:
        return _err(404, "NOT_FOUND", "We're still preparing data for this stock.",
                    "이 종목의 데이터가 아직 준비 중이에요.", rid)

    now = datetime.now(timezone.utc)
    state = market_state(exchange, now)
    as_of = datetime.fromisoformat(cached["as_of"].replace("Z", "+00:00"))
    stale = svc.is_stale(as_of, state, now)
    pc = cached.get("previous_close")
    price = cached["price"]
    change = round(price - pc, 4) if pc else None
    change_pct = round((price - pc) / pc * 100, 4) if pc else None
    return JSONResponse(content={
        "data": {
            "instrument": f"{symbol}:{exchange}",
            "name_en": ref.symbol, "name_ko": ref.symbol,
            "price": price, "currency": cached.get("currency", ref.currency),
            "change": change, "change_pct": change_pct,
            "previous_close": pc, "volume": cached.get("volume"),
            "day_high": cached.get("day_high"), "day_low": cached.get("day_low"),
            "market_state": state,
        },
        "meta": {"source": cached.get("source", "yfinance"), "data_as_of": cached["as_of"],
                 "is_stale": stale, "cache": "hit", "request_id": rid},
    })
```
(NOTE: `name_en/name_ko` use the symbol as a placeholder in M1a; the stocks repo gains name columns in M1b/dashboard work. The backend-design `/price` example shows names — flagged as a small follow-up, not blocking.)

Modify `backend/app/main.py` to mount the router:
```python
from app.routers import health, stocks
...
    app.include_router(health.router)
    app.include_router(stocks.router)
```

- [ ] **Step 4: Run → PASS** (and full suite green).  **Step 5: Commit** `feat: GET /stocks/{i}/price endpoint (cache-backed, honest staleness)`.

---

### Task 11: Scheduler wiring + /healthz heartbeat

**Files:** Create `backend/app/scheduler.py`; Modify `backend/app/main.py`, `backend/app/routers/health.py`; Create `backend/tests/test_scheduler.py`

- [ ] **Step 1: Failing test** — the scheduler builder registers the price jobs; heartbeat key check.

`backend/tests/test_scheduler.py`:
```python
from app.scheduler import build_scheduler, JOB_IDS


def test_scheduler_registers_price_jobs():
    sched = build_scheduler(run=False)
    ids = {j.id for j in sched.get_jobs()}
    assert {"poll_prices_krx", "poll_prices_us", "poll_indexes", "heartbeat"} <= ids
    assert set(JOB_IDS) <= ids
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backend/app/scheduler.py`:
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

JOB_IDS = ["poll_prices_krx", "poll_prices_us", "poll_indexes", "heartbeat"]


def build_scheduler(*, run: bool = True, jobs: dict | None = None) -> AsyncIOScheduler:
    """Register M1a jobs. `jobs` maps id->coroutine fn (injected in prod; no-op default
    so unit tests can introspect registration without real fetching)."""
    sched = AsyncIOScheduler(timezone="UTC")
    jobs = jobs or {jid: _noop for jid in JOB_IDS}
    sched.add_job(jobs["poll_prices_krx"], IntervalTrigger(minutes=1), id="poll_prices_krx",
                  max_instances=1, coalesce=True)
    sched.add_job(jobs["poll_prices_us"], IntervalTrigger(minutes=1), id="poll_prices_us",
                  max_instances=1, coalesce=True)
    sched.add_job(jobs["poll_indexes"], IntervalTrigger(minutes=1), id="poll_indexes",
                  max_instances=1, coalesce=True)
    sched.add_job(jobs["heartbeat"], IntervalTrigger(minutes=1), id="heartbeat",
                  max_instances=1, coalesce=True)
    if run:
        sched.start()
    return sched


async def _noop():
    return None
```

Wire into `backend/app/main.py` via lifespan (build real job callables binding settings/redis/providers), and add a heartbeat writer (`ops:heartbeat` key). Add to `health.py` a check that `ops:heartbeat` is < 3 min old (skipped if key absent so M0-style tests still pass). Full wiring code + a `lifespan` that calls `build_scheduler(run=True, jobs=...)` and `sched.shutdown()` on exit. (The unit test uses `run=False` + default no-op jobs; the live behavior is covered by the Task-end `docker compose up` smoke.)

- [ ] **Step 4: Run → PASS.**  **Step 5: Verify end-to-end:** `docker compose up -d --build`, wait ~70s for one poll cycle, `GET http://localhost/stocks/005930:KRX/price` → 200 with a real price (this is the live integration check); `docker compose down`.  **Step 6: Commit** `feat: APScheduler wiring for price_poller + healthz heartbeat`.

---

## Self-Review

**Spec coverage (vs roadmap M1a):** provider interface + retry + breaker (T1–T3) · yfinance + Finnhub + pykrx adapters (T5–T6) · region chain + `px:quote` cache + `is_stale`/`market_state` (T4, T8) · `price_poller` (T9, T11) · `/stocks/{i}/price` per `backend-design.md` §6.4 (T10) · scheduler (T11). ✓

**Real-data / offline-test reconciliation:** default suite is fakes + fakeredis + respx (deterministic, offline); real upstreams are `@pytest.mark.live` (excluded via `addopts = -m 'not live'`) plus the Task-11 `docker compose` smoke. No fabricated prices in app code. ✓

**Placeholder scan:** every step has complete code except Task 11's lifespan wiring, which is described rather than fully coded — **flagged**: expand to full code at execution (build real job callables, heartbeat writer, lifespan start/shutdown). All other tasks are complete.

**Type/name consistency:** `StockRef`/`PriceQuote` fields consistent across providers, service, repo, endpoint; cache key `px:quote:{symbol}:{exchange}` identical in service write + endpoint read + backend-design §5.1; `provider_chain(region, *, yfinance, finnhub, pykrx)` signature used identically in service + poller; `market_state` return set {open,closed,pre,post} matches the endpoint + backend-design §6.4. ✓

**Known deviations to log at execution:** (a) `/price` `name_en/ko` are symbol placeholders until the stocks repo carries names (M1b); (b) SQLite "latest stored bar" fallback in §6.4 is deferred (no bar store yet) — M1a serves from Redis only, 404 if uncached; (c) yfinance `fast_info` key names finalized by the live test; (d) per-stock (not batched) polling in v1.

---

## Execution Handoff

On approval, execute inline (`superpowers:executing-plans`) task-by-task with a check-in after each, updating `handoff.md` per task — same cadence as M0. Task 11 ends with a real `docker compose` price smoke. M1b (cross-market + FX) gets its own plan after M1a is green.
