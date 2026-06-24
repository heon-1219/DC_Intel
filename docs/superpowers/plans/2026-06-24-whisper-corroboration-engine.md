# Whisper-Number Corroboration Engine (AIWCE) — design + TDD plan

> **Goal:** for a stock with upcoming earnings, decide the **whisper EPS** and a **meaningfulness
> confidence**, OR honestly **abstain** ("no reliable whisper"), by retrieving candidate numbers from
> several **free** web sources and **iteratively comparing** them against each other and the official
> consensus. No LLM (free + local-first); deterministic + unit-testable; abstains rather than guesses —
> the same honesty ethos as the 52% prediction gate and the confirmed-vs-speculation intel badge.
> Full synthesized spec: workflow run `wf_b8e185b1-d5e` (3 competing designs → judged → merged).

## Why "not a regular RAG"
A regular RAG retrieves → stuffs an LLM → emits. AIWCE instead retrieves → **extracts numeric
candidates** → runs a **budgeted, convergence-driven loop** that COMPARES each new observation against
the current inlier consensus AND the trustworthy consensus anchor, stopping early on confirmation,
stopping when confirmation is provably impossible, and **abstaining** when evidence stays weak. The
"intelligence" is the corroboration algorithm, not generation.

## Pipeline (per upcoming-earnings stock; rerun daily, denser near the date)
Anchor (official consensus EPS) → for each source tier A=earningswhispers → B=estimize → C=websearch →
D=forum/stocktwits (cheapest/most-reliable first), fetch → **normalize** → **quarter/recency guard** →
**anchor-plausibility gate** → **per-obs weight** (cred × recency × plausibility × sign) → **dedup by
family** → **cluster by value agreement** → **robust weighted-median center + MAD outlier rejection** →
**multiplicative meaningfulness score** → **stop/continue/abstain** decision.

### Iteration (budgeted, convergence-driven — `WHISPER_MAX_ROUNDS=4`, `SOURCE_BUDGET=8`)
- **STOP-CONFIRM**: status would be `corroborated` (conf ≥75, ≥2 distinct families, dominance ≥0.5,
  dispersion ≤ tight) → emit, do NOT dilute with noisier tiers.
- **STOP-ABSTAIN-IMPOSSIBLE**: optimistic-completion bound — if every un-fetched source landed in the
  best cluster at max weight and still couldn't reach the floor, abstain now (no wasted CPU).
- **STOP-NO-GAIN**: a round added zero new inliers → diminishing returns, stop.
- **CONTINUE** otherwise (escalate A+B → C → D); **HARD-STOP** at MAX_ROUNDS / budget / ladder end.
- Fail-open on fetch errors (best-effort, like `retry.py`/`anomaly.py`).

### Meaningfulness score (computed on the WINNING cluster's INLIER set)
`confidence = round(100 · f_count · f_agree · f_cred · f_recency · f_anchor)` — **multiplicative so any
weak dimension caps the whole** (you can't buy a score by being loud). Then **caps**: coordinated→20,
single-family→40, all-stale→65, anchor-only-no-shift→scaled down. Bands (reuse credibility 50/75):
**corroborated ≥75** (+structure), **tentative 55–75**, **no_reliable_whisper <55**.

### Abstain reasons (checked in order; always prefer abstaining)
NO_ANCHOR, NO_EARNINGS_DATE, NO_OBSERVATIONS, ALL_FILTERED, INSUFFICIENT_INLIERS (with a high-trust
single-EarningsWhispers override → tentative≤40), NO_AGREEMENT, UNRESOLVED_CONTENTION, ANCHOR_DISTRUST,
COORDINATED, LOW_CONFIDENCE. Every abstention is a structured, logged, first-class result.

## Module layout (mirrors `app/intel/`)
```
app/intel/whisper_config.py          # env-overridable tunables (_f/_i helpers)
app/intel/whisper/
  models.py        # frozen dataclasses: WhisperObservation/Prior/Cluster/Result
  normalize.py     # parse EPS strings -> float ($/cents/loss/parens)   [DONE]
  robust.py        # weighted_median + scaled_mad + is_inlier            [DONE]
  weight.py        # quarter/recency guard, anchor-plausibility, per-obs weight
  cluster.py       # agreement clustering + family dedup
  score.py         # the 5-factor confidence, caps, status classification
  engine.py        # orchestrator: prior + iteration loop + result/abstain (fetchers INJECTED)
  fetchers/        # earningswhispers, websearch, ... (real scrapers; cassette-tested)
db/repositories/whisper.py + migration: whisper_numbers table
jobs/whisper_corroborator.py         # APScheduler job (like outcome_checker.py)
```

## TDD order & status
1. **config + normalize + robust (+tests)** — pure leaves. ← **this increment**
2. weight + cluster + score (+tests) — the pure scoring core.
3. engine (+test) — convergence loop with an injected `FakeFetcher` replaying cassettes.
4. fetchers — real free sources; parse tested vs **recorded real** cassettes (binding rule #4), `@live` refresh.
5. persistence (migration + repo) + scheduled job + wire to the earnings calendar.
6. API + UI: show whisper vs consensus + the corroborated/tentative badge; optional earnings→Telegram alert.

All decision math is pure functions (no I/O) → cassette replay reproduces the exact round sequence and
result, exactly like `credibility.py`/`gate.py`/`actuals.py`. Fixtures are recorded from REAL sources.
