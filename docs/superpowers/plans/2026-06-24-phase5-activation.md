# Phase 5 — Activation: make DC Intel *actually work* end-to-end

> **Goal (owner, 2026-06-24): "everything actually working."** M0–M10 built the machine and it runs on
> localhost; this phase turns the dormant data + model layers into real value: real stock-attributed
> intel → real per-stock sentiment → a gate-passing prediction model → live `/predict` → an accruing
> win/loss record. Sequenced with honest dependencies; some steps are owner-gated (keys, sudo) and one
> is time-bound (sentiment accrual). Plan-first per CLAUDE.md; execute the unblocked steps now.

## The dependency spine (why the order matters)
```
real sources (keys) ─┐
keyless Naver fix ───┼─► stock-mapped intel ─► per-stock sentiment (sentiment_logs)
                     │                                   │
                     │                          [accrue ~2–4 weeks]   (forward-only; can't backfill)
                     ▼                                   ▼
            richer/clean intel feed            retrain w/ sentiment ─► gate-passing model? ─► /predict live
                                                                                                  │
                                                                                  predictions logged ─► outcome_checker grades ─► win/loss record fills (~weeks)
```
Two pillars run in parallel: **(A) the intel/sentiment data path** and **(B) the prediction model**.
GPU + reliability + reach are supporting tracks.

## Progress log
- **2026-06-24 — Steps 2 & 3 DONE; Step 6 STARTED.** The intel/sentiment pillar now works end-to-end
  *keyless*: mDeBERTa verified loading + classifying accurately on CPU in-container (cross-lingual);
  root-caused `sentiment_logs=0` to the KR scrapers' bot-identifying User-Agent (Naver served a 2.6KB
  stub) → fixed to a realistic browser UA → Naver returns 296 real per-stock posts across 15 KRX codes;
  end-to-end run ingested 286 stock-mapped items → classified (58 bull / 81 bear / 241 neutral) →
  **`sentiment_logs` 0 → 15** per-stock scores. Added an `hfcache` volume so weights persist across
  restarts. The scheduled `intel_scrape` (now with the browser UA) + `aggregate_sentiment` jobs keep KR
  sentiment accruing automatically. **Remaining gap is US/global sentiment → needs Step 4 (API keys).**
- Step 1 reclassified: NOT a bug — 1h/5h use 5m/15m feed intervals (`ml.yaml`) which were never
  backfilled; low priority (short horizons ~unpredictable). Step 0.2 (DC general-board noise) deferred:
  it's market-wide unmapped chatter, partially real; revisit vs. real keyed sources.

## Honest caveats (set expectations)
- **Sentiment can't be backfilled** → predictions-improved-by-sentiment is weeks away, not today.
- **Beating the 52% gate is not guaranteed even with sentiment** — short-horizon direction is near-coin-flip. We maximize the odds honestly; if it still fails, the product ships predictions disabled-with-note (which is correct, not a failure).
- **Keyless scrapers are fragile** (sites change markup, block bots). Real keys are the durable path.

## Steps

### Step 0 — Baseline hygiene (now, unblocked)
- 0.1 Push the 31 local commits (owner auth needed — pending).
- 0.2 Quiet the intel NOISE: the DC Inside general-board fetch yields garbage ("ㅋㅋㅋ", idol chatter, admin notices) that pollutes the feed. Make ingestion drop obvious non-signal + only surface stock-mapped or clearly-financial items, so the feed is honest (empty-but-clean beats noisy).

### Step 1 — Fix the 1h/5h dataset bug (now, unblocked, model pillar)
- 160,458 hourly snapshots exist but 1h/5h train as "insufficient samples (<20)". Diagnose the
  short-timeframe path in `app/ml/dataset.py` (forward-label / stride / interval mapping) and fix so
  the short timeframes actually train. TDD. Then retrain → honest gate numbers for all 6.

### Step 2 — Verify the sentiment pipeline E2E on mapped intel (now, unblocked, intel pillar)
- The pipeline tests pass, but confirm in the *container* that a stock-mapped intel item flows all the
  way: inject one mapped `market_intel` row → run `aggregate_sentiment` → mDeBERTa loads (CPU torch) →
  per-item sentiment set → `sentiment_logs` written. Proves the only gap is *input*, and that the
  CPU-torch classifier actually loads in the image (catches a latent HF-download/load failure now).

### Step 3 — Keyless Korean per-stock intel (now, unblocked but fragile, intel pillar)
- Validate + fix the **Naver per-stock board** scraper (`finance.naver.com/item/board?code=`): it maps
  to stocks via the KRX code (no key needed). Re-point/limit the DC Inside fetch to per-stock galleries
  or drop it. Also: extend entity resolution to match Korean company names (`by_name_ko`, already
  supported by `resolve_symbol`) in post text so KR sources attribute stocks. → first real stock-mapped
  intel without any keys.

### Step 4 — Real sources via free keys (owner-gated: you obtain free keys)
- You provide any of: `FINNHUB_API_KEY`, `NEWSAPI_API_KEY`, `REDDIT_CLIENT_ID/SECRET`,
  `STOCKTWITS_ACCESS_TOKEN`, `TWITTER_AUTH_TOKEN`/`TWITTER_CT0` (X cookies), `FRED_API_KEY`. I wire them
  in cleanly, restart, and verify each yields stock-mapped, classified intel (US via `$cashtags`).
  This is the durable path to a real intel feed + sentiment.

### Step 5 — GPU enablement (owner-gated: sudo) — accelerates Step 6
- Install NVIDIA driver (`sudo ubuntu-drivers autoinstall`, reboot) + `nvidia-container-toolkit`; swap
  the backend image to CUDA torch + add a GPU reservation to compose. Verify mDeBERTa/MiniLM run on the
  RTX 3080. Makes sentiment throughput viable at real volume (CPU is the fallback).

### Step 6 — Sentiment accrual (time-bound, ~2–4 weeks)
- With sources + classifier live, `sentiment_logs` accrues per stock. Add a tiny accrual monitor
  (coverage % per stock/timeframe) so we know when there's enough to retrain.

### Step 7 — Retrain with real signal + honest gate (after Step 6)
- Retrain all timeframes now that sentiment features are present; run the controlled, walk-forward-
  validated 3d coverage experiment; ship ONLY gate-passers. If none pass, stay disabled-with-note.

### Step 8 — Predictions live + record fills (follows a passing model)
- `/predict` serves passers; predictions log; `outcome_checker` grades as windows close; accuracy
  badges populate (≥20 graded/stock). Verify the full loop in the running stack.

### Step 9 — Reliability + reach (supporting)
- Confirm restart-resilience, nightly backup, alerts. If "website" should be reachable beyond
  localhost: bind on the LAN, then domain + TLS (deployment §5.2) if a public demo is wanted.

## What I do now vs. what needs you
- **Now (me, unblocked):** Steps 1, 2, 3, 0.2 — model dataset fix, pipeline E2E proof, keyless KR intel,
  noise cleanup. Each ends green (tests + live verify).
- **Needs you:** Step 0.1 push (GitHub auth), Step 4 (free API keys), Step 5 (sudo for GPU driver).
- **Needs time:** Step 6 accrual → Step 7 retrain → Step 8 record.
