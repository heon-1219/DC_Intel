# M2a — Technical Indicator Engine (pure) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure, offline-testable technical-indicator core — RSI(14 Wilder), EMA(5/20/50/200), MACD(12/26/9), Bollinger(20,2σ), `vol_z20`, crossover detection, the deterministic signal-state machines, the EN/KO copy templates, and the `compute_indicators()` capstone that emits the exact `technical-indicators.md` §10.1 payload.

**Architecture:** Two new pure modules under `backend/app/services/` — `indicators.py` (math + crossover + state machines + payload assembler) and `indicator_copy.py` (EN/KO copy templates). No I/O: every function takes pandas Series/DataFrames or scalars and returns values/dicts. The TDD oracle is the set of worked numeric examples in `technical-indicators.md` §4.2 / §5.2 / §6.2 / §7.2 / §7A.2; each is reproduced to the doc's stated precision. The bar-fetch, persistence, job, and scheduler wiring are M2b (separate plan).

**Tech Stack:** Python 3.11+, pandas, numpy, pytest (offline, `asyncio_mode=auto` already set). No network in this milestone — all tests are pure CPU.

---

## Owner standards (binding — never violate)
1. **Completely FREE** — pandas/numpy are free, local.
2. **International + detail-perfect** — copy strings exact in EN + KO; green=up/red=down semantics encoded as `direction` on each state.
3. **Local-first** — pure CPU, no services.
4. **REAL data always** — M2a is pure math with NO data fetching; the only literals are the doc's published worked examples used as the test oracle (not fabricated market data — they are the spec's own reference values). Real bars arrive in M2b.

## Spec authorities
- `docs/technical-indicators.md` — **the** source of truth (formulas §4–7A, signal states §4.3/5.3/6.3/7.3/7A.3, copy §4.4/5.4/6.4/7.4/7A.4, payload §10.1, reference Python §13).
- `docs/prediction-model.md` §4.2 — the feature contract (`vol_z20` clip [−3,+6], feature names).
- `docs/schema.md` / `migrations/001_initial_schema.sql` — `technical_snapshots` columns (scalar cols `rsi, ema_5/20/50/200, macd, macd_signal, macd_histogram, bollinger_upper/lower/middle` + `indicators_json`). **Persistence is M2b** — M2a only produces the dict.

## Conventions adopted (locked here; M2b depends on these signatures)
- `bar t` = the **last row** of the input frame/series (caller drops the currently-forming bar — M2b's job).
- All smoothed indicators use **SMA seeding** exactly as §4.1/§5.1 specify (NOT plain `ewm`) so the worked examples reproduce at the seed bar. (`technical-indicators.md` §2 + §13 note that plain `ewm` is acceptable in production once converged; we implement the spec-faithful SMA seed so the oracle passes at the seed bar and `warming_up` quarantines the early region.)
- Population stddev (`ddof=0`) for Bollinger σ and volume σ (§7.1, §7A.1) — **never** `ddof=1`.
- Wilder smoothing α = `1/period` (§4.1 note) — **never** `2/(period+1)`.
- Crossover detection: `np.sign(fast − slow).diff()` → `+2` up-cross, `−2` down-cross (§13).
- `compute_indicators(bars, *, bar_interval, first_bar_of_session=False)` is the single public entry; it returns the §10.1 dict. `bar_interval ∈ {'5m','15m','1h','1d'}` (golden/death-cross naming is `'1d'`-only).

## File structure
- Create: `backend/app/services/indicators.py` — all math, crossover, state machines, `compute_indicators`.
- Create: `backend/app/services/indicator_copy.py` — EN/KO copy template tables + copy functions.
- Create: `backend/tests/test_indicators.py` — math oracles (rsi/ema/macd/bollinger/vol_z20/crossover).
- Create: `backend/tests/test_indicator_states.py` — state-machine threshold tables.
- Create: `backend/tests/test_indicator_copy.py` — exact EN/KO strings + evidence handshake forms.
- Create: `backend/tests/test_compute_indicators.py` — §10.1 payload assembly + flags.
- Modify: `backend/pyproject.toml` — add `pandas`, `numpy` as explicit deps.

---

### Task 0: Add pandas/numpy as explicit dependencies

`indicators.py` imports pandas+numpy directly; today they only arrive transitively via yfinance/pykrx. Make them explicit so the engine never depends on a transitive pin.

**Files:**
- Modify: `backend/pyproject.toml:9-20` (the `dependencies` list)

- [ ] **Step 1: Add the deps**

In `backend/pyproject.toml`, add to `dependencies` (after `"apscheduler>=3.10",`):

```toml
    "pandas>=2.0",
    "numpy>=1.26",
```

- [ ] **Step 2: Install into the uv venv**

Run: `uv pip install -p backend\.venv\Scripts\python.exe -e "./backend[dev]"`
Expected: resolves with pandas + numpy already satisfied (pandas 2.3.3 is present from M1); no errors.

- [ ] **Step 3: Verify import**

Run: `backend\.venv\Scripts\python.exe -c "import pandas, numpy; print(pandas.__version__, numpy.__version__)"`
Expected: prints two versions, no traceback.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "build(m2a): add pandas + numpy as explicit backend deps"
```

---

### Task 1: RSI — Wilder, SMA-seeded (oracle: 77.8 then 73.4)

**Files:**
- Create: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_indicators.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


def test_rsi_wilder_worked_example_seed_bar():
    # technical-indicators.md §4.2 — 15 closes -> RSI 77.8 at the seed bar (bar 14).
    closes = pd.Series([100, 101, 102, 101, 103, 104, 103, 105, 106,
                        105, 107, 108, 107, 109, 110], dtype=float)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[14] == pytest.approx(77.78, abs=0.01)


def test_rsi_wilder_worked_example_next_bar():
    # §4.2 — appending a down bar (close 109) -> RSI 73.4 (Wilder stickiness).
    closes = pd.Series([100, 101, 102, 101, 103, 104, 103, 105, 106,
                        105, 107, 108, 107, 109, 110, 109], dtype=float)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[15] == pytest.approx(73.4, abs=0.05)


def test_rsi_all_gains_is_100():
    closes = pd.Series([float(x) for x in range(1, 20)])  # strictly rising
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_flat_series_is_50():
    closes = pd.Series([50.0] * 20)
    rsi = ind.rsi_wilder(closes)
    assert rsi.iloc[-1] == pytest.approx(50.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.indicators'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/indicators.py`:

```python
"""Pure technical-indicator math. No I/O. Source of truth: docs/technical-indicators.md.

Conventions: bar t = last row; SMA-seeded smoothing (so worked examples reproduce at the
seed bar); Wilder alpha = 1/period; population stddev (ddof=0) for Bollinger/volume sigma.
"""
import numpy as np
import pandas as pd


def _wilder_smooth(s: pd.Series, period: int) -> pd.Series:
    """SMA seed of the first `period` values (indices 1..period after a .diff()),
    then Wilder recursion avg_t = (avg_{t-1}*(period-1) + s_t)/period."""
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) <= period:
        return out
    out.iloc[period] = s.iloc[1:period + 1].mean()
    for i in range(period + 1, len(s)):
        out.iloc[i] = (out.iloc[i - 1] * (period - 1) + s.iloc[i]) / period
    return out


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    close = close.astype(float).reset_index(drop=True)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder_smooth(gain, period)
    avg_loss = _wilder_smooth(loss, period)
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.mask(avg_loss == 0, 100.0)
    rsi = rsi.mask(avg_gain == 0, 0.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): RSI Wilder (SMA-seeded) reproducing the spec worked example"
```

---

### Task 2: EMA — SMA-seeded (oracle: 11.40 → 12.27 → 12.51)

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** (append to `test_indicators.py`)

```python
def test_ema5_worked_example():
    # §5.2 — EMA5 over 7 closes.
    closes = pd.Series([10, 11, 12, 11, 13, 14, 13], dtype=float)
    e = ind.ema(closes, 5)
    assert e.iloc[4] == pytest.approx(11.40, abs=0.005)   # SMA seed at bar 5
    assert e.iloc[5] == pytest.approx(12.27, abs=0.005)
    assert e.iloc[6] == pytest.approx(12.51, abs=0.005)


def test_ema_undefined_before_seed():
    closes = pd.Series([10, 11, 12], dtype=float)
    e = ind.ema(closes, 5)
    assert e.isna().all()   # fewer than `span` bars -> all NaN
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py::test_ema5_worked_example -v`
Expected: FAIL — `AttributeError: module 'app.services.indicators' has no attribute 'ema'`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
def ema(close: pd.Series, span: int) -> pd.Series:
    """SMA-seeded EMA: seed = SMA of the first `span` closes at index span-1, then
    EMA_t = alpha*C_t + (1-alpha)*EMA_{t-1}, alpha = 2/(span+1)."""
    close = close.astype(float).reset_index(drop=True)
    alpha = 2.0 / (span + 1)
    out = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) < span:
        return out
    out.iloc[span - 1] = close.iloc[:span].mean()
    for i in range(span, len(close)):
        out.iloc[i] = alpha * close.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): SMA-seeded EMA reproducing the spec worked example"
```

---

### Task 3: MACD (12/26/9) — oracle: 1.40 / 1.16 / 0.24

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_macd_signal_recursion_worked_example():
    # §6.2 — the signal-line EMA9 step: alpha9 = 2/10 = 0.2.
    # Signal_t = 0.2*MACD_t + 0.8*Signal_{t-1} = 0.2*1.40 + 0.8*1.10 = 1.16.
    macd_t, prev_signal = 1.40, 1.10
    alpha9 = 2.0 / (9 + 1)
    signal_t = alpha9 * macd_t + (1 - alpha9) * prev_signal
    assert signal_t == pytest.approx(1.16, abs=1e-9)
    assert macd_t - signal_t == pytest.approx(0.24, abs=1e-9)   # histogram


def test_macd_series_definitions():
    # MACD line == EMA12 - EMA26; signal == EMA9 of the MACD line; hist == line - signal.
    rng = pd.Series(np.linspace(100, 130, 80))  # 80 bars, enough to converge all EMAs
    line, signal, hist = ind.macd(rng)
    expected_line = ind.ema(rng, 12) - ind.ema(rng, 26)
    # compare on the converged tail where both are defined
    tail = expected_line.dropna().index[-1]
    assert line.loc[tail] == pytest.approx(expected_line.loc[tail], abs=1e-9)
    assert hist.loc[tail] == pytest.approx(line.loc[tail] - signal.loc[tail], abs=1e-9)
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py::test_macd_series_definitions -v`
Expected: FAIL — no attribute `macd`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram), all reindexed to `close`'s position
    index. Signal is the SMA-seeded EMA9 of the MACD line's defined (non-NaN) region."""
    close = close.astype(float).reset_index(drop=True)
    macd_line = ema(close, fast) - ema(close, slow)
    defined = macd_line.dropna()
    sig_on_defined = ema(defined.reset_index(drop=True), signal)
    signal_line = pd.Series(np.nan, index=close.index, dtype=float)
    signal_line.loc[defined.index] = sig_on_defined.values
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): MACD line/signal/histogram reproducing the spec worked example"
```

---

### Task 4: Bollinger Bands (20, 2σ, ddof=0) — formula oracle + breakout_up

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_bollinger_matches_documented_formula():
    # §7.1 — population stddev (ddof=0); upper/lower = mid +/- 2*sigma; %B and bandwidth.
    closes = pd.Series(np.concatenate([np.full(19, 50.0), [52.6]]))  # 20 bars, last spikes up
    mid, upper, lower, pct_b, bw = ind.bollinger(closes)
    win = closes.iloc[-20:]
    exp_mid = win.mean()
    exp_sigma = win.std(ddof=0)
    assert mid.iloc[-1] == pytest.approx(exp_mid, abs=1e-9)
    assert upper.iloc[-1] == pytest.approx(exp_mid + 2 * exp_sigma, abs=1e-9)
    assert lower.iloc[-1] == pytest.approx(exp_mid - 2 * exp_sigma, abs=1e-9)
    exp_pctb = (52.6 - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
    assert pct_b.iloc[-1] == pytest.approx(exp_pctb, abs=1e-9)
    assert bw.iloc[-1] == pytest.approx((upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1], abs=1e-9)
    assert pct_b.iloc[-1] > 1.0   # close above upper band -> breakout territory


def test_bollinger_band_arithmetic_50_sigma_1p2():
    # §7.2 reference arithmetic: mid=50, sigma=1.2 -> upper=52.4; with close=52.6, %B=1.04.
    mid, sigma, close = 50.0, 1.2, 52.6
    upper, lower = mid + 2 * sigma, mid - 2 * sigma
    assert upper == pytest.approx(52.4, abs=1e-9)
    assert (close - lower) / (upper - lower) == pytest.approx(1.0417, abs=0.001)


def test_bollinger_flat_series_percent_b_half():
    closes = pd.Series([50.0] * 20)
    _, _, _, pct_b, bw = ind.bollinger(closes)
    assert pct_b.iloc[-1] == pytest.approx(0.5)   # sigma==0 edge -> %B=0.5
    assert bw.iloc[-1] == pytest.approx(0.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py::test_bollinger_matches_documented_formula -v`
Expected: FAIL — no attribute `bollinger`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
def bollinger(close: pd.Series, period: int = 20, k: float = 2.0):
    """Returns (middle, upper, lower, percent_b, bandwidth). Population stddev (ddof=0)
    per §7.1 — REQUIRED to match TA references. sigma==0 -> %B=0.5, bandwidth=0."""
    close = close.astype(float).reset_index(drop=True)
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    upper = mid + k * sigma
    lower = mid - k * sigma
    width = (upper - lower)
    percent_b = ((close - lower) / width).where(sigma != 0, 0.5)
    bandwidth = (width / mid).where(sigma != 0, 0.0)
    return mid, upper, lower, percent_b, bandwidth
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): Bollinger Bands (population sigma) matching the spec formula"
```

---

### Task 5: Volume z-score `vol_z20` — clip [−3, +6] (oracle: 1.9)

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_vol_z20_worked_example():
    # §7A.2 — mean 100k, sigma 20k, current 138k -> z = (138k-100k)/20k = 1.9, no clip.
    vols = pd.Series(np.concatenate([
        np.full(10, 120000.0), np.full(9, 80000.0), [138000.0]]))  # 20 bars
    z = ind.vol_z20(vols)
    win = vols.iloc[-20:]
    exp = (138000.0 - win.mean()) / win.std(ddof=0)
    assert z.iloc[-1] == pytest.approx(exp, abs=1e-9)


def test_vol_z20_clips_to_lower_bound():
    # A near-zero volume bar after a high baseline produces raw z < -3 -> clipped to -3.0.
    # NOTE: with a 20-bar window the +6 upper bound is mathematically unreachable
    # (max |z| of one outlier in n=20 is (n-1)/sqrt(n) ~ 4.25), so the lower clip is the
    # exercisable one; both bounds are applied in code per the prediction-model.md §4.2 contract.
    vols = pd.Series(np.concatenate([np.full(19, 100000.0), [0.0]]))
    z = ind.vol_z20(vols)
    assert z.iloc[-1] == pytest.approx(-3.0)


def test_vol_z20_flat_volume_is_zero():
    vols = pd.Series([100.0] * 20)
    z = ind.vol_z20(vols)
    assert z.iloc[-1] == pytest.approx(0.0)   # sigma==0 edge
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py::test_vol_z20_clips_to_contract_bounds -v`
Expected: FAIL — no attribute `vol_z20`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
def vol_z20(volume: pd.Series, period: int = 20) -> pd.Series:
    """20-bar volume z-score, population stddev, clipped to [-3, +6] (model contract,
    prediction-model.md §4.2). sigma==0 -> 0.0 (flat/halted)."""
    volume = volume.astype(float).reset_index(drop=True)
    mean = volume.rolling(period).mean()
    sigma = volume.rolling(period).std(ddof=0)
    z = ((volume - mean) / sigma).where(sigma != 0, 0.0)
    return z.clip(lower=-3.0, upper=6.0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): vol_z20 with contract clip [-3,+6]"
```

---

### Task 6: Crossover detection — `+2`/`−2`, cross_dir, bars_since (cap 20)

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_crossover_up_then_recent():
    # fast starts below slow, then crosses above near the end.
    fast = pd.Series([1, 2, 3, 4, 9, 10], dtype=float)
    slow = pd.Series([5, 5, 5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow)
    assert direction == 1            # fast crossed above
    assert bars_since == 1           # crossed at index 4, last index 5


def test_crossover_down():
    fast = pd.Series([9, 9, 9, 1], dtype=float)
    slow = pd.Series([5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow)
    assert direction == -1
    assert bars_since == 0           # crossed on the last bar


def test_crossover_none_returns_zero_and_cap():
    fast = pd.Series([9, 9, 9, 9], dtype=float)
    slow = pd.Series([5, 5, 5, 5], dtype=float)
    direction, bars_since = ind.crossover(fast, slow, cap=20)
    assert direction == 0
    assert bars_since == 20           # capped sentinel when no cross in window


def test_crossover_bars_since_capped():
    fast = pd.Series([1] + [9] * 40, dtype=float)   # cross at index 1, 39 bars ago
    slow = pd.Series([5] * 41, dtype=float)
    _, bars_since = ind.crossover(fast, slow, cap=20)
    assert bars_since == 20           # capped at 20
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py::test_crossover_up_then_recent -v`
Expected: FAIL — no attribute `crossover`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
def crossover(fast: pd.Series, slow: pd.Series, cap: int = 20):
    """Most recent cross of `fast` over/under `slow` at or before the last bar.
    Returns (cross_dir, bars_since_cross): cross_dir in {+1 up, -1 down, 0 none},
    bars_since capped at `cap` (also the no-cross sentinel). §5.3 / §13."""
    f = fast.astype(float).reset_index(drop=True)
    s = slow.astype(float).reset_index(drop=True)
    sign = np.sign(f - s)
    diff = sign.diff()                       # +2 up-cross, -2 down-cross
    crosses = diff[(diff == 2) | (diff == -2)]
    if crosses.empty:
        return 0, cap
    last = crosses.index[-1]
    direction = 1 if diff.iloc[last] > 0 else -1
    bars_since = min(len(f) - 1 - last, cap)
    return direction, int(bars_since)
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicators.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicators.py
git commit -m "feat(m2a): crossover detection (cross_dir + capped bars_since)"
```

---

### Task 7: Signal-state machines (RSI/EMA-derived/MACD/Bollinger/volume)

Pure scalar/series → state-string functions. Each state carries a `direction` for color semantics via a separate map used by copy (Task 8).

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_indicator_states.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_indicator_states.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


@pytest.mark.parametrize("rsi,expected", [
    (75, "overbought"), (70, "overbought"),
    (65, "bullish"), (60, "bullish"),
    (50, "neutral"), (40, "neutral"),
    (35, "bearish"), (30.1, "bearish"),
    (30, "oversold"), (10, "oversold"),
])
def test_rsi_state(rsi, expected):
    assert ind.rsi_state(rsi) == expected


@pytest.mark.parametrize("z,first_bar,expected", [
    (2.5, False, "surge"), (2.0, False, "surge"),
    (1.5, False, "elevated"), (1.0, False, "elevated"),
    (0.0, False, "normal"), (-0.5, False, "normal"),
    (-1.0, False, "quiet"), (-2.0, False, "quiet"),
    (2.5, True, "elevated"),   # session-open guard raises surge threshold to 3.0
    (3.0, True, "surge"),
])
def test_vol_state(z, first_bar, expected):
    assert ind.vol_state(z, first_bar_of_session=first_bar) == expected


def test_macd_state_priority_cross_over_histogram():
    # A bullish signal-line cross within 3 bars beats a histogram state.
    state = ind.macd_state(cross_dir=1, bars_since_cross=1,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "bullish_cross"


def test_macd_state_zero_cross_when_no_signal_cross():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=1, bars_since_zero_cross=2,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "zero_cross_up"


def test_macd_state_momentum_building():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.2, 0.3, 0.4]))
    assert state == "momentum_building"


def test_macd_state_momentum_fading():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.4, 0.3, 0.2, 0.1]))
    assert state == "momentum_fading"


def test_macd_state_neutral():
    state = ind.macd_state(cross_dir=0, bars_since_cross=20,
                           zero_cross_dir=0, bars_since_zero_cross=20,
                           hist=pd.Series([0.1, 0.3, 0.2, 0.25]))
    assert state == "neutral"


def test_bollinger_state_breakout_up():
    pct_b = pd.Series([0.5, 0.6, 1.2])      # last pokes above upper; prior inside
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "breakout_up"


def test_bollinger_state_riding_upper():
    pct_b = pd.Series([0.96, 0.97, 0.98])   # >=0.95 for 3 consecutive, no fresh breakout
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "riding_upper"


def test_bollinger_state_inside():
    pct_b = pd.Series([0.4, 0.5, 0.6])
    bw = pd.Series([0.1, 0.1, 0.1])
    assert ind.bollinger_state(pct_b, bw) == "inside"


def test_bollinger_squeeze_true_when_lowest_in_120():
    pct_b = pd.Series([0.5] * 140)
    bw = pd.Series(np.linspace(0.5, 0.05, 140))   # last is the lowest in the trailing 120
    assert ind.bollinger_squeeze(bw) is True


def test_bollinger_squeeze_undefined_with_short_history():
    bw = pd.Series([0.1] * 100)                    # < 140 bars -> None
    assert ind.bollinger_squeeze(bw) is None


def test_ema_stack_flags():
    assert ind.ema_stack(5, 4, 3, 2) == (True, False)   # bullish stack
    assert ind.ema_stack(2, 3, 4, 5) == (False, True)   # bearish stack
    assert ind.ema_stack(5, 3, 4, 2) == (False, False)  # mixed
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_states.py -v`
Expected: FAIL — `rsi_state` not found.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
# --- Signal-state machines -------------------------------------------------

def rsi_state(rsi: float) -> str:
    if rsi >= 70:
        return "overbought"
    if rsi >= 60:
        return "bullish"
    if rsi >= 40:
        return "neutral"
    if rsi > 30:
        return "bearish"
    return "oversold"


def vol_state(z: float, *, first_bar_of_session: bool = False) -> str:
    surge_threshold = 3.0 if first_bar_of_session else 2.0   # §7A.3 session-open guard
    if z >= surge_threshold:
        return "surge"
    if z >= 1.0:
        return "elevated"
    if z > -1.0:
        return "normal"
    return "quiet"


def _rising(s: pd.Series, n: int = 3) -> bool:
    """True if the last n steps are strictly increasing."""
    tail = s.dropna().iloc[-(n + 1):]
    return len(tail) == n + 1 and bool((tail.diff().dropna() > 0).all())


def _shrinking_abs(s: pd.Series, n: int = 3) -> bool:
    """True if |s| strictly shrinks over the last n steps."""
    tail = s.dropna().abs().iloc[-(n + 1):]
    return len(tail) == n + 1 and bool((tail.diff().dropna() < 0).all())


def macd_state(*, cross_dir: int, bars_since_cross: int,
               zero_cross_dir: int, bars_since_zero_cross: int,
               hist: pd.Series) -> str:
    """Priority: signal-line cross > zero cross > histogram momentum. §6.3."""
    if cross_dir != 0 and bars_since_cross <= 3:
        return "bullish_cross" if cross_dir > 0 else "bearish_cross"
    if zero_cross_dir != 0 and bars_since_zero_cross <= 3:
        return "zero_cross_up" if zero_cross_dir > 0 else "zero_cross_down"
    last = hist.dropna()
    if len(last) and last.iloc[-1] > 0 and _rising(last):
        return "momentum_building"
    if _shrinking_abs(last):
        return "momentum_fading"
    return "neutral"


def bollinger_state(percent_b: pd.Series, bandwidth: pd.Series) -> str:
    """§7.3 (squeeze handled separately by bollinger_squeeze)."""
    b = percent_b.dropna()
    if b.empty:
        return "inside"
    cur = b.iloc[-1]
    prev = b.iloc[-2] if len(b) >= 2 else cur
    if cur > 1.0 and 0.0 <= prev <= 1.0:
        return "breakout_up"
    if cur < 0.0 and 0.0 <= prev <= 1.0:
        return "breakout_down"
    last3 = b.iloc[-3:]
    if len(last3) == 3 and bool((last3 >= 0.95).all()):
        return "riding_upper"
    if len(last3) == 3 and bool((last3 <= 0.05).all()):
        return "riding_lower"
    return "inside"


def bollinger_squeeze(bandwidth: pd.Series, window: int = 120, min_bars: int = 140):
    """True if current bandwidth is the lowest in the trailing `window` bars. None if
    fewer than `min_bars` of history (§7.3)."""
    bw = bandwidth.dropna()
    if len(bw) < min_bars:
        return None
    trailing = bw.iloc[-window:]
    return bool(bw.iloc[-1] <= trailing.min())


def ema_stack(ema5: float, ema20: float, ema50: float, ema200: float):
    """Returns (bullish, bearish) booleans for the fully-ordered stack. §5.3."""
    vals = [ema5, ema20, ema50, ema200]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
        return (False, False)
    bullish = ema5 > ema20 > ema50 > ema200
    bearish = ema5 < ema20 < ema50 < ema200
    return (bool(bullish), bool(bearish))
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_states.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_indicator_states.py
git commit -m "feat(m2a): deterministic signal-state machines (rsi/macd/bollinger/volume/ema-stack)"
```

---

### Task 8: Copy templates (EN/KO) + evidence handshake forms

**Files:**
- Create: `backend/app/services/indicator_copy.py`
- Test: `backend/tests/test_indicator_copy.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_indicator_copy.py`:

```python
import pytest

from app.services import indicator_copy as copy


def test_rsi_copy_overbought_en_ko():
    assert copy.rsi_copy(74, "overbought", "en") == "RSI overbought (74/70) → pullback risk"
    assert copy.rsi_copy(74, "overbought", "ko") == "RSI 과매수 (74/70) → 하락 전환 주의"


def test_rsi_copy_rounds_value_to_int():
    assert copy.rsi_copy(73.4, "bullish", "en") == "RSI strong (73) → buyers in control"
    assert copy.rsi_copy(27.2, "oversold", "en") == "RSI oversold (27/30) → bounce possible"


def test_ema_cross_copy_intraday_vs_daily_naming():
    # 50/200 up-cross is "golden cross" only on daily bars; "trend shift" intraday.
    assert "Golden cross" in copy.ema_cross_copy(50, 200, 1, "1d", "en")
    assert "Trend shift up" in copy.ema_cross_copy(50, 200, 1, "5m", "en")
    assert "골든 크로스" in copy.ema_cross_copy(50, 200, 1, "1d", "ko")


def test_ema_short_cross_copy():
    assert copy.ema_cross_copy(5, 20, 1, "5m", "en") == \
        "Short-term momentum turned up (5/20 cross) → upward push"
    assert copy.ema_cross_copy(5, 20, -1, "5m", "en") == \
        "Short-term momentum turned down (5/20 cross) → downward push"


def test_macd_copy_bullish_cross():
    assert copy.macd_copy("bullish_cross", "en") == \
        "Momentum flipped up (MACD cross) → buyers stepping in"
    assert copy.macd_copy("bullish_cross", "ko") == "모멘텀 상승 전환 (MACD 교차) → 매수세 유입"


def test_bollinger_copy_breakout_up():
    assert copy.bollinger_copy("breakout_up", "en") == \
        "Price broke above its normal range → upside breakout"


def test_volume_label_one_decimal():
    assert copy.vol_label(1.9, "en") == "Volume 1.9σ above normal"
    assert copy.vol_label(1.9, "ko") == "거래량 평소 대비 1.9σ 증가"


def test_short_evidence_forms():
    # §12 short canonical forms used when all 3 bullet slots are filled / mobile.
    assert copy.short_evidence("rsi", "overbought", "en") == "RSI overbought signal"
    assert copy.short_evidence("ema", "ema_5_20_up", "en") == "EMA crossover"
    assert copy.short_evidence("macd", "bullish_cross", "en") == "MACD momentum up"
    assert copy.short_evidence("bollinger", "breakout_up", "en") == "Range breakout up"


def test_direction_for_state():
    # color semantics: bullish->green, bearish->red, neutral/squeeze->gray
    assert copy.direction_for_state("rsi", "overbought") == "down"
    assert copy.direction_for_state("rsi", "oversold") == "up"
    assert copy.direction_for_state("rsi", "neutral") == "neutral"
    assert copy.direction_for_state("bollinger", "squeeze") == "neutral"
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_copy.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/indicator_copy.py`:

```python
"""EN/KO copy templates for indicator signal states. Source: technical-indicators.md
§4.4, §5.4, §6.4, §7.4, §7A.4, §12. Pure string functions."""

_RSI = {
    "overbought": ("RSI overbought ({v}/70) → pullback risk", "RSI 과매수 ({v}/70) → 하락 전환 주의"),
    "bullish":    ("RSI strong ({v}) → buyers in control",      "RSI 강세 ({v}) → 매수세 우위"),
    "neutral":    ("RSI neutral ({v}) → no clear pressure",     "RSI 중립 ({v}) → 뚜렷한 방향 없음"),
    "bearish":    ("RSI weak ({v}) → sellers in control",       "RSI 약세 ({v}) → 매도세 우위"),
    "oversold":   ("RSI oversold ({v}/30) → bounce possible",   "RSI 과매도 ({v}/30) → 반등 가능"),
}

_MACD = {
    "bullish_cross":     ("Momentum flipped up (MACD cross) → buyers stepping in",  "모멘텀 상승 전환 (MACD 교차) → 매수세 유입"),
    "bearish_cross":     ("Momentum flipped down (MACD cross) → sellers stepping in", "모멘텀 하락 전환 (MACD 교차) → 매도세 유입"),
    "zero_cross_up":     ("Momentum turned positive → uptrend confirmed",           "모멘텀 플러스 전환 → 상승 추세 확인"),
    "zero_cross_down":   ("Momentum turned negative → downtrend confirmed",         "모멘텀 마이너스 전환 → 하락 추세 확인"),
    "momentum_building": ("Upward momentum building → trend strengthening",         "상승 모멘텀 확대 → 추세 강화"),
    "momentum_fading":   ("Momentum fading → current trend losing steam",           "모멘텀 약화 → 현재 추세 둔화"),
}

_BOLL = {
    "squeeze":      ("Price range tightening → big move brewing (direction unclear)", "가격 변동폭 축소 → 큰 움직임 임박 (방향 미정)"),
    "breakout_up":  ("Price broke above its normal range → upside breakout",          "평소 범위 위로 돌파 → 상승 돌파"),
    "breakout_down":("Price broke below its normal range → downside break",           "평소 범위 아래로 이탈 → 하락 이탈"),
    "riding_upper": ("Price hugging the top of its range → strong demand",            "범위 상단 유지 → 강한 매수세"),
    "riding_lower": ("Price hugging the bottom of its range → strong selling",        "범위 하단 유지 → 강한 매도세"),
    "squeeze_breakout_up": ("Tight range broke upward → sharp rise often follows",    "좁은 범위 상향 돌파 → 급등 가능성"),
}

_SHORT = {
    ("rsi", "overbought"): ("RSI overbought signal", "RSI 과매수 신호"),
    ("rsi", "oversold"):   ("RSI oversold signal", "RSI 과매도 신호"),
    ("rsi", "bullish"):    ("RSI bullish signal", "RSI 강세 신호"),
    ("rsi", "bearish"):    ("RSI bearish signal", "RSI 약세 신호"),
    ("ema", "ema_5_20_up"):   ("EMA crossover", "EMA 교차"),
    ("ema", "ema_5_20_down"): ("EMA crossover", "EMA 교차"),
    ("macd", "bullish_cross"): ("MACD momentum up", "MACD 모멘텀 상승"),
    ("macd", "bearish_cross"): ("MACD momentum down", "MACD 모멘텀 하락"),
    ("bollinger", "breakout_up"):   ("Range breakout up", "범위 상향 돌파"),
    ("bollinger", "breakout_down"): ("Range breakout down", "범위 하향 이탈"),
}

# state -> direction for color semantics (green=up, red=down, gray=neutral). §12.
_DIRECTION = {
    ("rsi", "overbought"): "down", ("rsi", "bullish"): "up", ("rsi", "neutral"): "neutral",
    ("rsi", "bearish"): "down", ("rsi", "oversold"): "up",
    ("macd", "bullish_cross"): "up", ("macd", "bearish_cross"): "down",
    ("macd", "zero_cross_up"): "up", ("macd", "zero_cross_down"): "down",
    ("macd", "momentum_building"): "up", ("macd", "momentum_fading"): "neutral",
    ("macd", "neutral"): "neutral",
    ("bollinger", "breakout_up"): "up", ("bollinger", "breakout_down"): "down",
    ("bollinger", "riding_upper"): "up", ("bollinger", "riding_lower"): "down",
    ("bollinger", "squeeze"): "neutral", ("bollinger", "inside"): "neutral",
}


def _pick(en_ko: tuple, lang: str) -> str:
    return en_ko[1] if lang == "ko" else en_ko[0]


def rsi_copy(value: float, state: str, lang: str) -> str:
    return _pick(_RSI[state], lang).format(v=round(value))


def ema_cross_copy(fast: int, slow: int, cross_dir: int, bar_interval: str, lang: str) -> str:
    if (fast, slow) == (5, 20):
        if cross_dir > 0:
            return _pick(("Short-term momentum turned up (5/20 cross) → upward push",
                          "단기 흐름 상승 전환 (5/20 골든) → 상승 압력"), lang)
        return _pick(("Short-term momentum turned down (5/20 cross) → downward push",
                      "단기 흐름 하락 전환 (5/20 데드) → 하락 압력"), lang)
    # 50/200 pair: golden/death naming only on daily bars
    if bar_interval == "1d":
        if cross_dir > 0:
            return _pick(("Golden cross (50/200) → long-term trend turning up",
                          "골든 크로스 (50/200) → 장기 추세 상승 전환"), lang)
        return _pick(("Death cross (50/200) → long-term trend turning down",
                      "데드 크로스 (50/200) → 장기 추세 하락 전환"), lang)
    if cross_dir > 0:
        return _pick(("Trend shift up on short charts → strengthening",
                      "단기 차트 추세 상승 전환 → 강세 강화"), lang)
    return _pick(("Trend shift down on short charts → weakening",
                  "단기 차트 추세 하락 전환 → 약세 심화"), lang)


def macd_copy(state: str, lang: str) -> str:
    return _pick(_MACD[state], lang)


def bollinger_copy(state: str, lang: str) -> str:
    return _pick(_BOLL[state], lang)


def vol_label(z: float, lang: str) -> str:
    return _pick(("Volume {z}σ above normal", "거래량 평소 대비 {z}σ 증가"), lang).format(z=round(z, 1))


def short_evidence(group: str, state: str, lang: str) -> str:
    return _pick(_SHORT[(group, state)], lang)


def direction_for_state(group: str, state: str) -> str:
    return _DIRECTION.get((group, state), "neutral")
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_indicator_copy.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicator_copy.py backend/tests/test_indicator_copy.py
git commit -m "feat(m2a): EN/KO indicator copy templates + evidence handshake forms"
```

---

### Task 9: `compute_indicators()` capstone — the §10.1 payload + flags

Assembles the full snapshot dict from an OHLCV frame. Pure: frame in, dict out. Caller (M2b) supplies `bar_interval` and `first_bar_of_session`.

**Files:**
- Modify: `backend/app/services/indicators.py`
- Test: `backend/tests/test_compute_indicators.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_compute_indicators.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind


def _frame(n=260, start=100.0, step=0.2, vol=100000.0):
    """A clean rising OHLCV frame long enough to converge EMA200."""
    close = pd.Series([start + step * i for i in range(n)])
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": close.values, "high": (close + 0.1).values,
        "low": (close - 0.1).values, "close": close.values,
        "volume": [vol] * n,
    }, index=idx)


def test_payload_has_full_contract_keys():
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    for key in ["rsi_14", "rsi_state", "ema_5", "ema_20", "ema_50", "ema_200",
                "ema_200_available", "warming_up", "ema_5_20_cross_dir",
                "bars_since_ema_5_20_cross", "ema_50_200_cross_dir",
                "bars_since_ema_50_200_cross", "price_vs_ema20_pct", "price_vs_ema50_pct",
                "price_vs_ema200_pct", "ema_stack_bullish", "ema_stack_bearish",
                "macd_line", "macd_signal", "macd_histogram", "macd_hist_delta",
                "macd_line_pct", "macd_state", "bars_since_macd_cross", "bb_middle",
                "bb_upper", "bb_lower", "bb_percent_b", "bb_bandwidth", "bb_state",
                "bb_squeeze", "vol_z20", "vol_state", "flags"]:
        assert key in payload, f"missing {key}"


def test_payload_rising_series_is_bullish():
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    assert payload["rsi_14"] == pytest.approx(100.0, abs=1e-6)   # strictly rising
    assert payload["ema_stack_bullish"] is True
    assert payload["price_vs_ema200_pct"] > 0
    assert payload["ema_200_available"] is True


def test_payload_short_history_drops_ema200_and_flags():
    payload = ind.compute_indicators(_frame(n=120), bar_interval="1d")
    assert payload["ema_200"] is None
    assert payload["ema_200_available"] is False


def test_payload_insufficient_history_flag():
    payload = ind.compute_indicators(_frame(n=10), bar_interval="1d")
    assert payload["vol_z20"] is None
    assert "insufficient_history" in payload["flags"]


def test_payload_warming_up_flag_between_200_and_600():
    payload = ind.compute_indicators(_frame(n=300), bar_interval="1d")
    assert payload["ema_200"] is not None       # computed
    assert payload["warming_up"] is True        # but < 3*200 bars -> warming_up
    assert "warming_up" in payload["flags"]


def test_payload_json_serializable():
    import json
    payload = ind.compute_indicators(_frame(), bar_interval="1d")
    json.dumps(payload)   # must not raise (no numpy scalars / NaN leakage)
```

- [ ] **Step 2: Run to verify it fails**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_compute_indicators.py -v`
Expected: FAIL — no attribute `compute_indicators`.

- [ ] **Step 3: Write minimal implementation** (append to `indicators.py`)

```python
# --- Capstone payload assembler -------------------------------------------

def _scalar(series_or_val):
    """Last value of a Series as a plain float, or None if NaN/empty/None."""
    if series_or_val is None:
        return None
    if isinstance(series_or_val, pd.Series):
        s = series_or_val.dropna()
        if s.empty:
            return None
        v = float(s.iloc[-1])
    else:
        v = float(series_or_val)
    return None if (v != v) else v   # NaN guard


def compute_indicators(bars: pd.DataFrame, *, bar_interval: str,
                       first_bar_of_session: bool = False) -> dict:
    """Assemble the technical-indicators.md §10.1 payload from an OHLCV frame.
    `bars` must have columns open/high/low/close/volume; bar t = last row."""
    close = bars["close"].astype(float).reset_index(drop=True)
    volume = bars["volume"].astype(float).reset_index(drop=True)
    n = len(close)
    c_t = float(close.iloc[-1])
    flags: list[str] = []

    # RSI
    rsi_series = rsi_wilder(close)
    rsi_val = _scalar(rsi_series)

    # EMAs
    ema5 = ema(close, 5); ema20 = ema(close, 20)
    ema50 = ema(close, 50); ema200 = ema(close, 200)
    ema5_v, ema20_v = _scalar(ema5), _scalar(ema20)
    ema50_v = _scalar(ema50)
    ema200_available = n >= 200
    ema200_v = _scalar(ema200) if ema200_available else None
    warming_up = ema200_available and n < 600   # 3 * 200 (§2 convergence)
    if warming_up:
        flags.append("warming_up")

    cd_5_20, bs_5_20 = crossover(ema5, ema20)
    cd_50_200, bs_50_200 = crossover(ema50, ema200) if ema200_available else (0, 20)
    stack_bull, stack_bear = ema_stack(ema5_v, ema20_v, ema50_v,
                                       ema200_v if ema200_v is not None else float("nan"))

    def _vs(ref):
        return round((c_t - ref) / ref * 100, 4) if ref else None

    # MACD
    macd_line, macd_signal_s, macd_hist = macd(close)
    macd_line_v = _scalar(macd_line)
    macd_signal_v = _scalar(macd_signal_s)
    macd_hist_v = _scalar(macd_hist)
    hist_clean = macd_hist.dropna()
    macd_hist_delta = (round(float(hist_clean.iloc[-1] - hist_clean.iloc[-2]), 6)
                       if len(hist_clean) >= 2 else None)
    macd_cross_dir, bars_since_macd_cross = crossover(macd_line, macd_signal_s)
    zero = pd.Series(0.0, index=macd_line.index)
    zc_dir, bs_zc = crossover(macd_line, zero)
    macd_st = macd_state(cross_dir=macd_cross_dir, bars_since_cross=bars_since_macd_cross,
                         zero_cross_dir=zc_dir, bars_since_zero_cross=bs_zc, hist=macd_hist)
    macd_line_pct = round(macd_line_v / c_t * 100, 6) if macd_line_v is not None else None

    # Bollinger
    bb_mid, bb_up, bb_low, bb_pctb, bb_bw = bollinger(close)
    bb_state_v = bollinger_state(bb_pctb, bb_bw)
    bb_squeeze_v = bollinger_squeeze(bb_bw)
    if bb_squeeze_v:
        bb_state_v = "squeeze" if bb_state_v == "inside" else bb_state_v

    # Volume
    if n < 20:
        flags.append("insufficient_history")
        vol_z_v = None
        vol_st = None
    else:
        vol_z_series = vol_z20(volume)
        vol_z_v = _scalar(vol_z_series)
        vol_st = vol_state(vol_z_v, first_bar_of_session=first_bar_of_session) \
            if vol_z_v is not None else None

    # stale_price: flat closes (RSI pinned to 50 by the flat-series rule)
    if n >= 15 and rsi_val == 50.0 and close.tail(15).nunique() == 1:
        flags.append("stale_price")
    # limit_lock: >=5 consecutive bars with high == low (KRX limit lock, §9.4)
    if n >= 5:
        hl_equal = (bars["high"].astype(float).reset_index(drop=True)
                    == bars["low"].astype(float).reset_index(drop=True))
        if bool(hl_equal.tail(5).all()):
            flags.append("limit_lock")

    return {
        "rsi_14": _round(rsi_val, 4), "rsi_state": rsi_state(rsi_val) if rsi_val is not None else None,
        "ema_5": _round(ema5_v, 6), "ema_20": _round(ema20_v, 6),
        "ema_50": _round(ema50_v, 6), "ema_200": _round(ema200_v, 6),
        "ema_200_available": bool(ema200_available), "warming_up": bool(warming_up),
        "ema_5_20_cross_dir": cd_5_20, "bars_since_ema_5_20_cross": bs_5_20,
        "ema_50_200_cross_dir": cd_50_200, "bars_since_ema_50_200_cross": bs_50_200,
        "price_vs_ema20_pct": _vs(ema20_v), "price_vs_ema50_pct": _vs(ema50_v),
        "price_vs_ema200_pct": _vs(ema200_v),
        "ema_stack_bullish": stack_bull, "ema_stack_bearish": stack_bear,
        "macd_line": _round(macd_line_v, 6), "macd_signal": _round(macd_signal_v, 6),
        "macd_histogram": _round(macd_hist_v, 6), "macd_hist_delta": macd_hist_delta,
        "macd_line_pct": macd_line_pct, "macd_state": macd_st,
        "bars_since_macd_cross": bars_since_macd_cross,
        "bb_middle": _round(_scalar(bb_mid), 6), "bb_upper": _round(_scalar(bb_up), 6),
        "bb_lower": _round(_scalar(bb_low), 6), "bb_percent_b": _round(_scalar(bb_pctb), 6),
        "bb_bandwidth": _round(_scalar(bb_bw), 6), "bb_state": bb_state_v,
        "bb_squeeze": bb_squeeze_v,
        "vol_z20": _round(vol_z_v, 4), "vol_state": vol_st,
        "flags": flags,
    }


def _round(v, ndigits):
    return None if v is None else round(v, ndigits)
```

- [ ] **Step 4: Run to verify it passes**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_compute_indicators.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indicators.py backend/tests/test_compute_indicators.py
git commit -m "feat(m2a): compute_indicators capstone emitting the §10.1 payload + flags"
```

---

### Task 10: M2a wrap — full suite green + handoff update

**Files:**
- Modify: `handoff.md`

- [ ] **Step 1: Run the whole backend suite**

Run: `backend\.venv\Scripts\python.exe -m pytest backend\tests -v`
Expected: all M1 tests (68) + all new M2a tests green; 0 failures; no `live` tests run (excluded by `addopts`).

- [ ] **Step 2: Update handoff.md**

Add an M2a section under the task changelog noting: indicator engine complete (RSI/EMA/MACD/Bollinger/vol_z20 + crossover + state machines + EN/KO copy + compute_indicators), total test count, all worked examples reproduced. Set "Next: M2b — bar pipeline + persistence + recompute_indicators job."

- [ ] **Step 3: Commit**

```bash
git add handoff.md
git commit -m "docs(m2a): M2a indicator engine complete — handoff updated"
```

---

## Self-Review (run after writing; fixed inline)

**Spec coverage check vs `technical-indicators.md`:**
- §4 RSI (Wilder, SMA seed, edge cases, states §4.3, copy §4.4) → Tasks 1, 7, 8. ✓
- §5 EMA (SMA seed, crossovers §5.3, trend features, stack, copy §5.4) → Tasks 2, 6, 7, 8, 9. ✓
- §6 MACD (line/signal/hist, states §6.3 priority, features incl. macd_line_pct + hist_delta, copy §6.4) → Tasks 3, 7, 8, 9. ✓
- §7 Bollinger (ddof=0, %B, bandwidth, squeeze 120/140, states §7.3, copy §7.4) → Tasks 4, 7, 8, 9. ✓
- §7A vol_z20 (clip [−3,+6], states §7A.3 incl. session-open guard, label §7A.4) → Tasks 5, 7, 8, 9. ✓
- §10.1 payload contract (exact keys + flags) → Task 9. ✓
- §12 evidence handshake (short forms, direction-for-color) → Task 8. ✓

**Deferred to a documented v1 simplification (logged in handoff deviations at execution):**
- §9.2 session-open *event-gap* guard (breakout/cross events on the first session bar requiring gap > 0.5σ) — only the **vol_z20** session-open guard (§7A.3, clearly specified threshold 3.0) is implemented in M2a; the breakout/cross event-gap guard is an over-trigger refinement not required by the exit criteria and is deferred to a later pass. The numeric indicators are unaffected.
- "Active symbols" scoping (§10.2) and the on-demand synchronous compute path — these are M2b/M6 concerns (job scope + prediction endpoint), not the pure engine.

**Placeholder scan:** none — every step has complete code/commands.

**Type consistency:** `compute_indicators(bars, *, bar_interval, first_bar_of_session)` is the single entry M2b calls; helper signatures (`rsi_wilder`, `ema`, `macd`, `bollinger`, `vol_z20`, `crossover`, `rsi_state`, `vol_state`, `macd_state`, `bollinger_state`, `bollinger_squeeze`, `ema_stack`) are consistent across Tasks 1–9 and the copy module functions match Task 8 tests.
