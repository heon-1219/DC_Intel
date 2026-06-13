# DC Intel — Handoff / Working State

Living doc to prevent information loss across check-ins and sessions. **Update after every task.**

## TL;DR — where we are right now
- **Phase:** 4 (implementation). Docs approved; building.
- **Milestone:** M0 — Foundation & scaffolding.
- **Current task:** Task 1 ✅ DONE (commit `75ae3b8`). **Next: Task 2** (settings/`config.py`).
- **Mode:** inline execution; check in with owner after each task (commit boundary).
- **Branch:** `main` (fresh repo, git init'd in Task 1).

## How to resume (cold start)
1. Read this file, then the two plan docs:
   - `docs/superpowers/plans/2026-06-13-dc-intel-phase4-roadmap.md` (program roadmap, M0–M10 + test strategy)
   - `docs/superpowers/plans/2026-06-13-dc-intel-m0-foundation.md` (current milestone, task-by-task TDD)
2. `git log --oneline` → see completed tasks (each task = one commit).
3. Continue from the first unchecked `- [ ]` task in the current milestone plan.
4. Backend tests: `backend\.venv\Scripts\python.exe -m pytest backend\tests -v` (or `uv run --project backend pytest`).

## Environment (verified 2026-06-13)
- OS: Windows 11, PowerShell. **Project path has spaces + Korean — always quote paths.**
- git 2.46.0 · python 3.14.0 · pip 26.0.1 · docker 28.5.2 · **uv 0.9.26**.
- ⚠️ **Local Python is 3.14; Docker runtime is `python:3.11-slim`.** M0's light deps are fine on 3.14 (pydantic-core 2.46.4 had a 3.14 wheel). **Watch for wheel gaps at M5** (xgboost / transformers / scikit-learn) — if a dep has no 3.14 wheel, `uv venv --python 3.11` (uv fetches it for free) to match Docker.
- **venv is managed with `uv`** (owner standard) at `backend/.venv`. Recreate / install:
  `uv venv --python 3.14 backend\.venv` then `uv pip install -p backend\.venv\Scripts\python.exe -e "./backend[dev]"`.
  Run tests/commands via `backend\.venv\Scripts\python.exe -m pytest backend\tests` (activation does NOT persist across tool calls) or `uv run --project backend pytest`.

## Owner standards (binding — never violate)
1. **Completely FREE** — no paid APIs/hosting/tiers.
2. **International + detail-perfect UI** — green=up/red=down; aligned, no layout shift, all component states (`ui-ux.md` P9).
3. **Local-first** — runs on localhost; `DOMAIN=localhost`; alerts→local log; backups→local volume.
4. **REAL data always** — the app uses live data only; TESTS use cassettes recorded from real APIs (deterministic, offline) — never fabricated data.

## Key decisions (see docs/open-questions.md for the full decision log)
- Twitter/X = v1 via **logged-in session scraping** (personal-use, free); cookies `TWITTER_AUTH_TOKEN`+`TWITTER_CT0`; **no detection-evasion infra**. `data-sources.md` §4.1.
- Calendar = free Investing.com scrape; NewsAPI free tier; KRX fallback = pykrx; Korean community scraping approved with safeguards.
- Doc authorities: `schema.md` (tables) · `backend-design.md` (endpoints/Redis keys/rate limits) · `deployment-architecture.md` (env registry) · `prediction-model.md` (reasoning_json/explainability).

## Deviations from the plan (log)
- **Task 1 `pyproject.toml`:** added `[build-system]` (setuptools) + `[tool.setuptools.packages.find] include=["app*"]`. The plan omitted these; without them an editable install fails ("Multiple top-level packages discovered" — `app` and `tests`). No behavior change, just makes `pip install -e` discover only `app`.
- **Task 1 `.gitignore`:** added `*.egg-info/` (editable install creates `backend/dc_intel_backend.egg-info/`).
- **Task 1 commit scope:** broadened the first commit to the full repo baseline (the pre-existing approved `docs/` + `handoff.md` + scaffold) instead of scaffold-only, since this is a fresh repo and leaving 15 doc files untracked would be messy. Subsequent tasks commit per-task as planned.

## Task changelog
- **Task 1 ✅** (`75ae3b8`) — git init on `main`; `.gitignore`; `backend/pyproject.toml`; `app` package; pytest harness; smoke test PASS (1 passed); editable install OK. Working tree clean.
- **Post-Task-1 (owner request):** switched the venv from stdlib `venv`/`pip` to **`uv`**. Rebuilt `backend/.venv` with `uv venv` + `uv pip install`; smoke test still PASS. Plan (M0) commands + README updated to uv. (uv venv is gitignored; no code change, so folded into the next commit.)
- Task 2 — next: `config.py` (pydantic-settings, JWT_SECRET validation, `sqlite_path`).
