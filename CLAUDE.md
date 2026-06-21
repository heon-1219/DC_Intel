# DC Intel — project guide for Claude (and humans)

Beginner-friendly short-term stock-direction prediction platform (Korea KRX + US + global;
Korean/English UI) fusing technical indicators, multi-source sentiment, social-media market intel,
and an economic calendar, with **honest** win/loss tracking. Built in explicit phases M0–M10.

> **START HERE every session: read [`handoff.md`](handoff.md)** — the living resume doc (current
> milestone, what's done, what's next, cold-start steps). Update it after every task.

## Owner's 4 binding standards (apply to ALL work — never violate)
1. **Completely FREE** — no paid APIs / hosting / tiers.
2. **International standards** (green = up / red = down) + detail-perfect, clean UI (alignment, no
   layout shift).
3. **LOCAL-FIRST** — runs on localhost via docker-compose; alerts are log-file based.
4. **REAL data always** — the running app uses live data only. TESTS use fixtures/cassettes recorded
   from real APIs (deterministic, offline) — **never fabricated/synthetic values**.

## Process constraints
- **Plan first, then build.** Per-milestone plans live in `docs/superpowers/plans/` (written
  just-in-time). The program roadmap is `docs/superpowers/plans/2026-06-13-dc-intel-phase4-roadmap.md`.
- **TDD** (red → green → refactor) for all features/fixes.
- **Stop at milestones, not every task.** Commit per task; push to `origin/main`.
- Docs in `/docs` were owner-approved before any code (Phase 1–3).

## Stack & layout
Python 3.11 · FastAPI + APScheduler (in-process jobs) · SQLite (WAL) · Redis cache · Docker + Caddy.
ML (optional `[ml]` dep group, lazy-imported): mDeBERTa zero-shot sentiment + MiniLM clustering
(torch CPU), scikit-learn / xgboost / shap for the prediction models.
- `backend/app/` — `routers/`, `db/repositories/`, `jobs/`, `services/`, `providers/`, `calendar/`,
  `intel/`, `sentiment/`, `ml/` (features/serving/training), `tracking/` (labels + win-loss), `auth/`.
- `backend/migrations/` — numbered SQL. `config/` — seeds + ml.yaml + economic_events/sectors yaml.
- `docs/` — design docs (source of truth) + `docs/superpowers/plans/` (roadmap + milestone plans).

## Setup on a NEW machine (e.g. homeserver)
```
git clone <repo> && cd "DC Intel"
uv venv --python 3.11 backend/.venv                 # uv fetches 3.11 if absent
uv pip install -p backend/.venv/Scripts/python.exe -e "./backend[dev,ml]"   # ml is heavy (CPU torch)
cp .env.example .env                                # then edit: JWT_SECRET is REQUIRED (>=32 chars)
backend/.venv/Scripts/python.exe -m pytest backend/tests        # 495 passing, 8 live deselected
docker compose up -d --build                        # http://localhost/healthz = 200
```
On Linux/macOS the venv python is `backend/.venv/bin/python`. Set `$env:UV_HTTP_TIMEOUT=900` (or
`export UV_HTTP_TIMEOUT=900`) before installing — the CPU torch wheel is large.

## NOT in git (regenerate on a new machine)
- `backend/.venv/` — rebuild via uv (above).
- `backend/data/` — local SQLite incl. `m5c.db` (the M5 training scratch DB). The **running app**
  uses its own docker `dbdata` volume (migrated + seeded at container startup), not these.
- `backend/models/**/*.pkl` — trained model weights. **Manifests (`manifest.json`) ARE tracked.**
  ⚠️ Without the `.pkl`, `GET /stocks/{i}/predict` returns 503 MODEL_UNAVAILABLE (disabled-with-note).
  To restore serving on a new machine: re-run M5 training (`python -m app.ml.backfill` then
  `python -m app.ml.train --timeframe 5d ...`) OR copy the `.pkl` over manually. (See handoff.md.)

## Cross-session memory note
Claude's auto-memory (`~/.claude/projects/.../memory/`) is **machine-local and does NOT transfer via
git**. This file + `handoff.md` + the plan docs are the authoritative, repo-tracked project memory.

## Status (see handoff.md for detail)
✅ M0–M7 complete (foundation, market data, indicators, economic calendar, sentiment/intel, ML
feature builder + training, prediction serving + auth, win-loss tracking). **NEXT: M8** (dashboard
endpoints) → M9 (React frontend, incl. the overnight board) → M10 (hardening + deploy).
