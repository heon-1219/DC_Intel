# M3a — Economic-Calendar Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use `- [ ]`. This is the first of three M3 slices: **M3a ingestion** → M3b serving+actuals → M3c event-study. Because M3 is large, this plan gives full code for the non-obvious pieces (scraper parser, canonicalize, impact precedence, merge/dedup, repo upsert) and precise specs + test lists for the rest.

**Goal:** Ingest real economic-calendar events (next 14 days) into `economic_events` from the Investing.com scrape (primary) + official-free composite (FRED dates + Finnhub earnings/IPO + FOMC/BOK/BOJ seed JSON), canonicalized via a registry, with impact assignment (§5) and `affected_stocks_json` (§6, static block), driven by the `sync_calendar` job with circuit-breaker fallback promotion.

**Architecture:** `app/calendar/` package: provider adapters behind a `CalendarProvider` protocol → `RawEvent`s → canonicalize (registry) → assign impact → build affected → merge/dedup → upsert into `economic_events`. Pure logic (canonicalize/impact/affected/merge) is unit-tested; providers are tested with real captured cassettes where reachable (Investing.com needs no key) and live-marked + shape fixtures otherwise (FRED/Finnhub keys).

**Tech Stack:** Python 3.11+, httpx, PyYAML, beautifulsoup4 (HTML parsing), aiosqlite, APScheduler. `zoneinfo` for tz. Offline tests deterministic; real upstreams behind `@pytest.mark.live` + docker smoke (M3c).

---

## Owner standards (binding)
1. **FREE** — Investing.com (no key), FRED (free key), Finnhub (free tier), seeds (static). $0.
2. **International + detail-perfect** — EN/KO titles + plain summaries from the registry; UTC-only storage; impact indicator NOT green/red (amber intensity — UI concern, M9).
3. **Local-first** — in-process APScheduler job; degrades gracefully when a key/source is absent.
4. **REAL data always** — running app scrapes/fetches live. **Tests:** capture a REAL Investing.com cassette (reachable without a key) for the brittle parser; FRED/Finnhub get `@pytest.mark.live` tests + offline parser fixtures whose **shape matches the live-verified contract** (values illustrative for parser plumbing; documented). Seed dates are REAL (researched from federalreserve.gov / bok.or.kr / boj.or.jp). **No detection-evasion** in the scraper.

## Forced deferrals (dependencies not yet built)
- Per-user `affects_your_stocks` overlay + alert banner (§9) → **M6** (needs JWT auth). The M3b endpoint ships anonymous → `affects_your_stocks: null`.
- `reasoning_json.high_impact_events[]` snapshot at prediction time (§13.1) → **M6** (prediction serving).
- `actual_vs_forecast` derivation + `fetch_actual` jobs → **M3b**. Event-study `history` block → **M3c** (stays absent until then).

## Researched real data (source of truth for the seed files — DO NOT fabricate)

**FOMC 2026** (federalreserve.gov; 2:00 PM ET, exact): `2026-01-28T19:00:00Z`, `2026-03-18T18:00:00Z`, `2026-04-29T18:00:00Z`, `2026-06-17T18:00:00Z`, `2026-07-29T18:00:00Z`, `2026-09-16T18:00:00Z`, `2026-10-28T18:00:00Z`, `2026-12-09T19:00:00Z`. (EST=19:00Z in Jan/Dec, EDT=18:00Z Mar–Oct.)

**BOK 2026** base-rate decisions (bok.or.kr; dates exact, **time unpublished** → 10:00 KST = `01:00:00Z` estimate, `time_estimated: true`): `2026-01-15`, `2026-02-26`, `2026-04-10` (Fri), `2026-05-28`, `2026-07-16`, `2026-08-27`, `2026-10-22`, `2026-11-26`.

**BOJ 2026** MPM decisions (boj.or.jp; dates exact, **time unpublished** → 12:30 JST = `03:30:00Z` estimate, matches spec §12 example, `time_estimated: true`): `2026-01-23`, `2026-03-19`, `2026-04-28`, `2026-06-16`, `2026-07-31`, `2026-09-18`, `2026-10-30`, `2026-12-18`.

**API contracts** (verified 2026-06-16):
- **FRED** `GET https://api.stlouisfed.org/fred/releases/dates?api_key=&file_type=json&include_release_dates_with_no_data=true&realtime_start=<today>&sort_order=asc&limit=1000` → `{release_dates:[{release_id,release_name,date:"YYYY-MM-DD"}]}`. Dates only, no time/forecast. CPI=10, Employment Situation=50, GDP=53. Free key required (`FRED_API_KEY`); 400 if missing/bad.
- **Finnhub** `GET https://finnhub.io/api/v1/calendar/earnings?from=&to=&token=` → `{earningsCalendar:[{symbol,date,epsEstimate,epsActual,revenueEstimate,revenueActual,hour(bmo|amc|dmh),quarter,year}]}`; `/calendar/ipo?from=&to=&token=` → `{ipoCalendar:[{date,exchange,name,numberOfShares,price(string),status,symbol,totalSharesValue}]}`. Free tier covers earnings+IPO (US). `/calendar/economic` is premium → 401/403 on free; **do not use**.
- **Investing.com** `POST https://www.investing.com/economic-calendar/Service/getCalendarFilteredData`, `Content-Type: application/x-www-form-urlencoded`, **MANDATORY** headers `X-Requested-With: XMLHttpRequest` + realistic Chrome `User-Agent` + `Referer: https://www.investing.com/economic-calendar/` (without them → 301 empty). Body: `currentTab=custom&dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD&timeZone=55&timeFilter=timeOnly&submitFilters=1&limit_from=0` plus repeated `country[]=` / `importance[]=`. Returns JSON (Content-Type text/html) `{data:"<tr…> HTML", rows_num, params:{offsetSec,…}}`. Parse rows: day divider `<td class="theDay" id="theDayUNIXTS">`; event `<tr id="eventRowId_<id>" event_attr_ID="<series>" data-event-datetime="YYYY/MM/DD HH:MM:SS">`; cells → time (`td.time`), country (`span[title]` + currency text), importance (`data-img_key=bull1|bull2|bull3`), name (`td.event a`), actual (`#eventActual_<id>`, color class greenFont/redFont/blackFont), forecast (`#eventForecast_<id>`), previous (`#eventPrevious_<id>`). Times are in the requested `timeZone`; `params.offsetSec` converts to UTC. No Cloudflare challenge at 3–5 req/day.

## File structure
```
config/
  economic_events.yaml      # event-type registry (§4)
  sectors.yaml              # sector map (§6.3)
  fomc_2026.json bok_2026.json boj_2026.json   # central-bank seeds (real dates)
backend/app/calendar/
  __init__.py
  models.py                 # RawEvent, RawActual, CanonEvent dataclasses
  registry.py               # load economic_events.yaml + sectors.yaml; match(provider,name)->event_type
  canonicalize.py           # RawEvent -> CanonEvent (event_type, titles, country, impact, affected)
  impact.py                 # assign_impact(registry_entry, provider_importance) -> (level, source)
  affected.py               # build_affected_json(registry_entry) -> dict (static block, §6)
  merge.py                  # dedup canonical events by (event_type, date); seed time wins for central banks
  providers/
    base.py                 # CalendarProvider protocol + helpers
    seed_provider.py        # reads config/*_2026.json
    fred_provider.py        # FRED releases/dates
    finnhub_calendar_provider.py   # earnings + ipo
    investing_provider.py   # the scraper + HTML parser
backend/app/db/repositories/economic_events.py   # upsert + list_in_range + mark_cancelled
backend/app/jobs/calendar_sync.py   # sync_calendar job (orchestrates the above)
```
Plus: `config/.env.example` + `app/config.py` (`fred_api_key`); `app/scheduler.py` (+`sync_calendar` 06:30 KST = 21:30 UTC cron); `pyproject.toml` (PyYAML, beautifulsoup4). Tests mirror under `backend/tests/`, cassettes in `backend/tests/cassettes/`.

---

### Task 0: deps + config
- Add `pyyaml>=6.0`, `beautifulsoup4>=4.12` to `pyproject.toml` dependencies; `uv pip install -e "./backend[dev]"`.
- `app/config.py`: add `fred_api_key: str = ""`. `config/.env.example`: add `FRED_API_KEY=` (free key from https://fred.stlouisfed.org/docs/api/api_key.html; degrade gracefully if blank) near the existing `FINNHUB_API_KEY`.
- Verify import of yaml + bs4. Commit `build(m3a): add pyyaml + beautifulsoup4; FRED_API_KEY setting`.

### Task 1: dataclasses (`app/calendar/models.py`)
```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class RawEvent:
    provider: str                 # 'investing_com'|'fred'|'finnhub'|'seed'
    provider_event_id: str | None
    raw_name: str                 # provider's event name (for registry match)
    country: str                  # ISO-2 or 'GLOBAL'
    scheduled_utc: datetime       # tz-aware UTC
    importance: int | None = None # provider scale 1..3 (investing bulls); None otherwise
    forecast: float | None = None
    previous: float | None = None
    actual: float | None = None
    unit: str | None = None
    time_estimated: bool = False  # seeds with unpublished times
    extra: dict = field(default_factory=dict)  # e.g. earnings symbol/exchange/eps

@dataclass(frozen=True)
class CanonEvent:
    event_type: str
    event_name: str               # English display title
    title_ko: str | None
    country: str
    event_time: str               # ISO-8601 UTC 'Z'
    impact_level: str             # 'high'|'medium'|'low'
    impact_source: str            # 'override'|'provider'|'default'
    provider: str
    provider_event_id: str | None
    affected_json: dict
    raw: RawEvent
```
Tests: construction + frozen. Commit.

### Task 2: registry (`config/economic_events.yaml` + `app/calendar/registry.py`)
YAML carries the §4 registry. Seed it with the §5.1 override-table event types + worked examples: `us_cpi, us_fomc_rate_decision, kr_bok_rate_decision, jp_boj_rate_decision, us_nonfarm_payrolls, us_gdp_advance, us_retail_sales, us_ppi, kr_cpi, kr_unemployment, ecb_rate_decision, us_michigan_sentiment`, plus a shared `mega_cap_high` anchor list (AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,AVGO,005930,000660). Each entry: `titles{en,ko}`, `plain_summary{en,ko}`, `country`, `provider_match{investing_com:[…], fred:[…], finnhub:[…]}`, `impact_override`, `surprise_polarity`, `neutral_band_abs`, `affected{indexes,sectors,stocks}`. Example entry = the §4 `us_cpi` block verbatim.

`registry.py`:
```python
import functools, yaml
from pathlib import Path

@functools.lru_cache
def load_registry(path: str) -> dict: ...      # {event_type: entry}
@functools.lru_cache
def load_sectors(path: str) -> dict: ...        # {code: {name_en,name_ko,proxy,members}}

def match_event_type(registry: dict, provider: str, raw_name: str) -> str | None:
    """Case-insensitive match of raw_name against each entry's provider_match[provider]."""
    name = raw_name.strip().lower()
    for etype, e in registry.items():
        for alias in (e.get("provider_match", {}).get(provider, []) or []):
            if alias.strip().lower() == name:
                return etype
    return None

def auto_slug(country: str, raw_name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    return f"{country.lower()}_{s}"
```
Tests: load real YAML (≥12 types); match "CPI (YoY)"→us_cpi; unmatched→None; auto_slug. Commit.

### Task 3: sector map (`config/sectors.yaml` + loader covered by Task 2) — ~10 sectors from §6.3 (semiconductors, banks_us, autos, software, …) with proxy + members. Tests: load, semiconductors has 005930:KRX member. Commit.

### Task 4: seed files + seed provider
Create `config/fomc_2026.json` / `bok_2026.json` / `boj_2026.json` using the **researched real dates** above. Shape:
```json
{ "event_type": "us_fomc_rate_decision", "country": "US", "provider": "seed",
  "time_estimated": false,
  "events": [ {"event_time": "2026-06-17T18:00:00Z", "provider_event_id": "fomc-2026-06-17"}, ... ] }
```
(BOK/BOJ: `time_estimated: true`, times `01:00:00Z` / `03:30:00Z`.)

`seed_provider.py`: `SeedProvider(config_dir)` implements `fetch_scheduled(start,end)` → reads the 3 JSON files, yields a `RawEvent` per event in range (provider='seed', raw_name from a fixed map of event_type→display name, country, scheduled_utc, time_estimated). Tests: returns FOMC Jun 17 in-range; out-of-range filtered; time_estimated propagates. Commit.

### Task 5: FRED provider (`fred_provider.py`)
`FredProvider(api_key)` `fetch_scheduled(start,end)`: if no key → return `[]` (graceful). Else httpx GET releases/dates with the documented params; map each `{release_id,release_name,date}` to a `RawEvent` (provider='fred', provider_event_id=f"{release_id}:{date}", raw_name=release_name, country='US', scheduled_utc = date at 12:30 UTC placeholder for 08:30 ET — **note: FRED gives date only**; use 13:30Z winter/12:30Z summer? Keep simple: 12:30:00Z (08:30 EDT) as the documented convention, refined by the scrape/actual job). Errors → ProviderError. Tests: offline parse of a shape fixture (3 releases) → 3 RawEvents, CPI maps via registry; empty key → []; `@pytest.mark.live` real fetch (skipped without key). Commit.

### Task 6: Finnhub calendar provider (`finnhub_calendar_provider.py`)
`FinnhubCalendarProvider(api_key)` `fetch_scheduled(start,end)`: earnings → `RawEvent(provider='finnhub', provider_event_id=f"earnings:{symbol}:{date}", raw_name=f"{symbol} earnings", country='US', scheduled_utc from date+hour(bmo=13:00Z/amc=21:00Z/dmh=16:00Z placeholder), extra={symbol,exchange:'NASDAQ'?,eps*,rev*})`. (Exchange resolution: look up symbol in `stocks` table later; for the RawEvent default exchange unknown→resolved in canonicalize/sync.) IPO optional (low priority; can be a follow-up). No key → []. Tests: shape fixture → earnings RawEvents; `@pytest.mark.live`. Commit.

### Task 7: Investing.com scraper (`investing_provider.py`) — capture a REAL cassette
- `_HEADERS` (Chrome UA + `X-Requested-With: XMLHttpRequest` + Referer). `_build_body(start,end,timezone_id=55)`.
- `fetch_scheduled(start,end)`: httpx POST; `data = resp.json()["data"]`; parse via `parse_rows(html, offset_sec)`.
- `parse_rows(html, offset_sec)` (pure, BeautifulSoup): iterate; track current day from `td.theDay` (unix ts → date); for each `tr.js-event-item`: id from `eventRowId_`, datetime from `data-event-datetime` (in requested tz) converted to UTC via `offset_sec`, country from `span[title]`, importance from `data-img_key` (bull1/2/3→1/2/3), name from `td.event a`, actual/forecast/previous from the `#event{Actual,Forecast,Previous}_<id>` cells (numeric parse, strip %/K/B). Defensive: skip holiday/all-day rows (no bull icon).
- **Cassette capture (a real step):** `python -c "<post once>"` saving the raw JSON to `backend/tests/cassettes/investing_calendar.json`. Parser test loads the cassette → asserts ≥1 RawEvent with sane fields. Also a `@pytest.mark.live` test hitting the real endpoint.
Representative parser core:
```python
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

def parse_rows(html: str, offset_sec: int) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("tr.js-event-item"):
        rid = tr.get("id", "").replace("eventRowId_", "")
        dt_local = tr.get("data-event-datetime")               # 'YYYY/MM/DD HH:MM:SS'
        if not dt_local:
            continue
        naive = datetime.strptime(dt_local, "%Y/%m/%d %H:%M:%S")
        scheduled_utc = (naive - timedelta(seconds=offset_sec)).replace(tzinfo=timezone.utc)
        flag = tr.select_one("td.flagCur span")
        country = (flag.get("title") if flag else "") or "GLOBAL"
        imp_cell = tr.select_one("td.sentiment")
        img = (imp_cell.get("data-img_key") if imp_cell else "") or ""
        importance = int(img[-1]) if img.startswith("bull") else None
        a = tr.select_one("td.event a")
        name = a.get_text(strip=True) if a else tr.select_one("td.event").get_text(strip=True)
        def num(css):
            el = tr.select_one(css)
            t = el.get_text(strip=True).replace("%", "").replace(",", "") if el else ""
            try: return float(t)
            except ValueError: return None
        out.append(RawEvent(
            provider="investing_com", provider_event_id=rid or None, raw_name=name,
            country=_iso2(country), scheduled_utc=scheduled_utc, importance=importance,
            actual=num(f"#eventActual_{rid}"), forecast=num(f"#eventForecast_{rid}"),
            previous=num(f"#eventPrevious_{rid}")))
    return out
```
Commit.

### Task 8: impact (`impact.py`)
```python
_PROVIDER_SCALE = {3: "high", 2: "medium", 1: "low"}
def assign_impact(entry: dict | None, provider_importance: int | None) -> tuple[str, str]:
    if entry and entry.get("impact_override"):
        return entry["impact_override"], "override"
    if provider_importance in _PROVIDER_SCALE:
        return _PROVIDER_SCALE[provider_importance], "provider"
    return "low", "default"
```
Tests: override wins over provider; provider maps 3→high; default→(low,default). Commit.

### Task 9: affected (`affected.py`)
`build_affected_json(entry, sectors)` → §6.1 shape from the registry `affected` block (scope from heuristics: stock if entry has stocks, else macro), `history: None`. Earnings events: scope='stock', stocks=[{symbol,exchange,relation:'direct'}], sectors from membership. Tests: us_cpi→macro+indexes; NVDA earnings→stock. Commit.

### Task 10: canonicalize (`canonicalize.py`)
`canonicalize(raw, registry, sectors, stocks_index)` → CanonEvent: match event_type (registry or auto_slug; earnings → `earnings:{sym}:{exch}`), titles (registry or raw_name), impact via Task 8, affected via Task 9, event_time = ISO Z. Tests: investing CPI raw → us_cpi + high/override + macro affected; unmatched → auto_slug + (low|provider). Commit.

### Task 11: economic_events repo (`repositories/economic_events.py`)
`upsert_event(con, canon)` → INSERT … ON CONFLICT on the two unique keys. Because SQLite supports one ON CONFLICT target, implement: try match by (provider, provider_event_id) when id present (UNIQUE(provider,provider_event_id)); else by (event_type, event_time) (UNIQUE(event_type,event_time)). Use `INSERT … ON CONFLICT(provider,provider_event_id) DO UPDATE …` when id present, else `ON CONFLICT(event_type,event_time) DO UPDATE …`. Update mutable cols (impact_level, impact_source, affected_stocks_json, title_ko, event_name, status, updated_at), preserve created_at, never delete. `list_in_range(con, from_utc, to_utc, impact=None, country=None)`; `mark_cancelled(con, ids)`. `await con.commit()`. Tests (temp DB): insert→read; upsert by provider id overwrites; upsert by (type,time) merges; list_in_range filters. Commit.

### Task 12: merge/dedup (`merge.py`)
`dedup(canon_events)`: group by `(event_type, date(event_time))`; within a group pick the authoritative row — **seed > investing_com > fred > finnhub** for the time/title; merge forecast/previous/actual/importance from whichever has them; keep one CanonEvent. Ensures seed central-bank time wins (§11.2) and the same event from two providers collapses (§15). Tests: seed FOMC + investing FOMC same day → one row with seed time; CPI from investing + fred same day → one row. Commit.

### Task 13: `sync_calendar` job (`jobs/calendar_sync.py`) + scheduler
```python
async def sync_calendar(db_path, redis, breaker, *, providers, registry_path, sectors_path,
                        config_dir, now=None, horizon_days=14) -> int:
    """Fetch all providers for [now, now+horizon], canonicalize, dedup, upsert. Returns rows upserted.
    Breaker source 'investing_calendar'; on scrape failure record + continue (composite still merges).
    Writes ops key cal:last_synced_at (M3b reads it for data_stale)."""
```
- `providers` = ordered list incl. InvestingProvider, SeedProvider, FredProvider, FinnhubCalendarProvider (injected; seeds + composite always merged; breaker tracks the scrape).
- Each provider's `fetch_scheduled` wrapped in try/except → on error record_failure(source), continue. Seeds never fail.
- Canonicalize all RawEvents → dedup → upsert each.
- Set `cal:last_synced_at` = now ISO; invalidate `cal:*` list keys (delete keys matching) — M3b populates them.
- Register in `app/scheduler.py`: add `sync_calendar` to `JOB_INTERVALS`? No — it's a **daily cron at 21:30 UTC** (06:30 KST), not an interval. Add a `CronTrigger(hour=21, minute=30)` job alongside the interval jobs. Extend `build_scheduler` to also register cron jobs from a `JOB_CRONS = {"sync_calendar": (21,30)}` map. Wire the real callable in `main.py` lifespan (build providers with settings keys).
- Tests: with FakeCalendarProviders (one yielding 2 events, one raising) → upserts 2, breaker failure recorded, `cal:last_synced_at` set; scheduler registers `sync_calendar` as a CronTrigger at 21:30 UTC. Commit.

### Task 14: handoff + memory + commit/push
Update handoff (M3a done, providers + sync job live, test count) + memory; set Next: M3b. Commit + push.

---

## Self-Review
- Spec coverage: §2 providers (Tasks 4–7), §4 registry (Task 2), §5 impact (Task 8), §6 affected static (Task 9), §3 repo/upsert keys (Task 11), §11.1/§11.2 sync+seed-wins (Tasks 12–13), §10 UTC-only (all providers emit tz-aware UTC). Event-study history (§8) + actuals (§7) deferred to M3c/M3b (documented). ✓
- REAL-data: Investing.com real cassette + live; seeds real dates; FRED/Finnhub live + shape fixtures (documented compromise). ✓
- Deferrals (affects/auth, prediction snapshot) logged. ✓
- Placeholder scan: FRED/Finnhub intraday times are documented placeholders (date-only sources) refined by the scrape/actual job — flagged, not silent. ✓
