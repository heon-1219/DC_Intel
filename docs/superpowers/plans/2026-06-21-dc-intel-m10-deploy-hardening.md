# M10 — Hardening & local-first deploy

> **Plan written 2026-06-21** (just-in-time). Final milestone. Implements `deployment-architecture.md`
> (§2.3 backups, §8.3 alerts, §7 containers/env, §11 launch checklist). Owner directive: full build.
> The `docker compose` end-to-end smoke is the gate but Docker isn't installed on this server — code +
> config + pytest are done now; the smoke runs once Docker is installed (same blocker as M8/M9).

## Goal & exit criteria
`docker compose up` brings the whole app (backend + redis + Caddy-served SPA) up on localhost at $0
with real data; nightly local backup; alerts → `logs/alerts.log`; `win_rate_monitor` job; README +
env guide; the §11 checklist passes. Code gate: full pytest green; frontend build green.

## Slices (commit per slice; `feat(m10x)`; TDD the backend jobs)

### M10a — Config + alert channel
- config.py + .env.example: `win_rate_alert_threshold` (0.50), `win_rate_warn_threshold` (0.52),
  `win_rate_min_sample` (30), `alert_webhook_url` (""), `backup_bucket` (""),
  `alert_log_path` ("logs/alerts.log"), `backup_dir` ("/data/backups").
- `app/core/alerts.py` `emit_alert(level, event, message, **fields)`: append one JSON line to
  `alert_log_path` (mkdir parent) + structlog console line; if `alert_webhook_url` set, best-effort
  POST (skipped/again-fail-open in v1). Test: writes a parseable JSON line at the right level.

### M10b — win_rate_monitor job (§8.3)
- `app/jobs/win_rate_monitor.py` `run_win_rate_monitor(db, *, now)`: per timeframe, rolling 7-day
  directional win rate from prediction_outcomes JOIN predictions (created_at ≥ now−7d, dedup like
  accuracy_stats), with ≥ `win_rate_min_sample` graded → `< alert` ERROR, else `< warn` WARN, with
  model_version in the message. Returns the alerts list. Test: seed outcomes → ERROR/WARN/none + the
  min-sample gate.

### M10c — db_backup job (§2.3)
- `app/jobs/db_backup.py` `run_db_backup(db, backup_dir, *, now)`: `VACUUM INTO
  '<backup_dir>/dcintel-YYYYMMDD.db'` (online-safe; never cp a live WAL DB); prune to 14 daily + 8
  weekly; on exception → ERROR alert. Returns the snapshot path. Test: creates the snapshot file +
  retention prune keeps the right set.

### M10d — Scheduler + lifespan wiring
- scheduler.py JOB_CRONS: `win_rate_monitor` 22:30 UTC (07:30 KST), `db_backup` 19:30 UTC (04:30 KST).
  main.py lifespan binds them. Update the test_scheduler exact-set assertion.

### M10e — Caddy + frontend image + compose
- Caddyfile: `handle /api/*` → strip_prefix /api → reverse_proxy backend:8000; everything else →
  `file_server` with `try_files {path} /index.html` (SPA routing); CSP + security headers (§9.2).
- `frontend/Dockerfile`: node build stage (`npm ci && npm run build`) → caddy stage serving /srv +
  the Caddyfile.
- docker-compose.yml: `web` builds from frontend/Dockerfile; backend gains `TRUST_PROXY=true`,
  `ALERT_LOG_PATH=/data/logs/alerts.log`, `BACKUP_DIR=/data/backups`, and the win-rate envs.
- entrypoint.sh: `mkdir -p /data/backups /data/logs` before launch.

### M10f — README + env guide + verify + docs
- README: local-first run (`docker compose up -d --build`), the venv/pytest dev loop (Linux paths),
  frontend dev (`npm run dev`), free-key setup (FINNHUB/FRED/NEWSAPI/Reddit/StockTwits + X cookies),
  model-`.pkl` restore note, the §11 launch checklist.
- Full backend pytest green + frontend build green. Update handoff/roadmap/CLAUDE → M10 COMPLETE
  (pending the Docker smoke). Note the §11 docker checklist as the remaining manual gate.

## Deferred (documented)
- Docker e2e smoke (needs Docker on the server). Cloud demo (BACKUP_BUCKET/DOMAIN/uptime pinger) —
  §5.2 optional, out of local-first v1. model_retrain weekly job + metrics_rollup — noted in §3.1 but
  outside the win-loss/serving core already shipped; flag as v1.1 ops if not built here.
