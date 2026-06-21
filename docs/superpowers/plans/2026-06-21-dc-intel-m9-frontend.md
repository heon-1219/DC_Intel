# M9 — Frontend (React + Vite SPA)

> **Plan written 2026-06-21** (just-in-time). Implements `docs/ui-ux.md` (the UI source of truth)
> against the live M8 API. Owner directive: **full build, nothing omitted** (no features deferred
> beyond ui-ux.md §11's explicit v1.1/v2 list). Stop questions until the end of the whole program.

## Goal & exit criteria
A complete beginner-facing React SPA covering every ui-ux.md screen, in KO/EN, against the 12 live
endpoints. Exit: `tsc --noEmit` clean, `vite build` succeeds, `vitest` green; all components ship the
five states (loading/loaded/empty/error/stale); green=up everywhere + never-color-alone; polling
matches §3.1; P9 detail-perfect (token grid, tabular-nums, no layout shift). Full-stack visual
verification happens in M10 once Docker is up (frontend served by Caddy).

## Stack (ui-ux.md §10, pinned)
Vite + **React 18** + TypeScript · React Router v6 · TanStack Query v5 · Recharts (accuracy-trend +
index/mini charts) + hand-rolled SVG sparklines · CSS Modules + the §4 token sheet · `useT()` + two
JSON dicts (no i18n framework) · native `Intl.*` · vitest + @testing-library/react + jsdom for tests.
Node via nvm (v24); `frontend/` is a new top-level dir (roadmap repo layout).

## Resolved conventions (from ui-ux.md)
- Token `dc_intel_token` (localStorage); 401 → clear + redirect `/login?returnTo=`. Lang
  `dc_intel_lang`, region `dc_intel_region`.
- Polling per §3.1 with ±10% jitter + Page Visibility pause + 3-fail backoff (cap 10 min); predict +
  accuracy + history are fetch-on-action/navigation (no interval).
- Direction: green=up/red=down/gray=neutral in BOTH locales, always arrow+word. Confirmed=blue,
  Unconfirmed=amber (never green/red). Impact dots+label+color.
- Server copy (evidence/calendar/intel) comes pre-localized via `?lang=`; UI never translates it.
- `MIN_ACCURACY_SAMPLE = 20`: win_rate shown only when graded ≥ 20 (badge, trending, history trend).
- Cross-market diff: server computes all; client renders native-currency price + signed % + tooltip
  (§6.3); stale leg (>10min) → gray diff. KRW in EN locale shows `85,000 KRW` (code suffix).
- Mandatory disclaimer footer on dashboard + prediction view (fixed copy §1).

## Slices (commit per slice; `feat(m9x)`; verify tsc+build, vitest where logic warrants)

### M9a — Scaffold + tokens + i18n foundation
Vite react-ts in `frontend/`; pin react@18/react-dom@18; add react-router-dom@6, @tanstack/react-query@5,
recharts, and dev vitest/@testing-library/jsdom. `styles/tokens.css` (verbatim §4.1–4.3 + base reset,
Pretendard stack, tabular-nums). `locales/en.json`+`ko.json` (the §5.1 table + every key the screens
need, flat ICU `{n}`). `hooks/useT.ts` (lang context + ICU interpolation), `i18n` LangProvider.
`vitest.config`, a `useT` interpolation test. **Verify:** tsc + build + vitest.

### M9b — API layer + auth + routing shell
`api/types.ts` (typed `{data,meta}` envelope + response models for all 12 endpoints, matching
backend-design §6). `api/client.ts` (base URL from `VITE_API_BASE` default `''` (same-origin via
Caddy), JWT header, unwrap envelope, throw typed ApiError on `{error}`, 401 → clear token + redirect
returnTo, AbortController support). `hooks/useAuth.tsx` (AuthProvider: token in localStorage,
login/register/logout, current path returnTo). `routes.tsx` (React Router: /login /register /dashboard
/stocks/:listing(+/history) /* 404; ProtectedRoute). `App.tsx`/`main.tsx` (QueryClientProvider + Lang
+ Auth providers + RouterProvider). Test: client unwraps envelope + raises on error + 401 path.

### M9c — common components + hooks
`Sparkline` (pure SVG, aria-hidden, sign-colored, flat-line empty), `Chips` (StaleChip/MarketClosedChip
§3.2), `ErrorCard` (tap-to-retry ≥44px), `Disclaimer`, `CountdownLabel` (1-min tick, 1-s under 1h,
"happening now" at T-0, aria-live=off). `hooks/useMarketHours.ts` (client KRX/US sessions; server
state wins when present), `hooks/usePolling.ts` (refetchInterval + jitter + visibility + backoff helper
wrapping TanStack options), `lib/format.ts` (Intl money per §6.3, relative-time "x ago", diff color).
Tests: sparkline path, market-hours, money/diff formatting, countdown.

### M9d — Auth screens + header
`pages/Login`, `pages/Register` (centered card, email+password client validation, show/hide toggle,
pending-disabled, inline error copy §2.2, link to other form, forgot-password static copy).
`components/AppHeader` (logo→dashboard, search field opening the overlay, `한국어|EN` toggle, logout).
Test: login form validation + submit calls auth.login + error rendering.

### M9e — Dashboard
`pages/Dashboard` (grid per §4.4, mobile order indexes→trending→intel→calendar, disclaimer footer).
`IndexStrip` (5 fixed tiles: level/%Δ/▲▼▬/mini chart/open-closed dot), `TrendingCarousel`+`TrendingCard`
(region KR|US toggle persisted; merge gainers+losers → top10 by |%Δ|; sparkline; win-rate badge per
§7.4.5 threshold; tap→stock), `EconCalendar`+`CountdownLabel` (high-first, cap 8 + show-all, impact
dots+label, dual local times, live countdown), `IntelFeed`+`IntelCard`+`ConfirmBadge`+`CredibilityMeter`+
`AnomalyBanner` (badge mandatory else skip; credibility meter+band; sentiment chip; snippet original
lang; coordinated label; anomaly headline; prepend-on-top + "↑ n new" pill). All five states + polling.

### M9f — Search overlay
`SearchOverlay` (bottom-sheet xs / anchored panel ≥md; `/` shortcut; debounce 250ms; min 2 chars (1 if
Hangul); AbortController per keystroke; TanStack 60s cache; combobox/listbox/aria-activedescendant;
↑/↓ over listings, Enter select, Esc close, focus trap+restore) + `ListingRow` (company group → all
listings, native-currency price, primary tag, diff chip via §6.3, "—" when uncached). Test: debounce/min
chars + diff display + keyboard select.

### M9g — Prediction view
`pages/StockView` (header price+dayΔ polled; Prediction|History tabs; 40/60 on lg; disclaimer).
`DirectionIndicator` (30vh, giant arrow + display phrase + window caption; cross-fade), `ConfidenceScore`
(display % + 0–100 track + 50 marker + tooltip), `TimeframeSelector` (radiogroup, 6 fixed, default 24h,
per-session persist), `EvidenceList` (≤3 rows icon+phrase+contribution bar to 100), `AccuracyBadge`
(normal/collecting per MIN_SAMPLE=20, bg by win-rate band, per-tf tooltip), `CrossMarketTable`
(table≥md/stacked xs, diff §6.3, row nav, closed-leg stale), stock `IntelFeed` variant. Tests: accuracy
badge threshold + evidence bars + timeframe default/persist.

### M9h — History tab
`HistoryLog` (rows When|Timeframe|Predicted|Result|Outcome; status→✅/❌/⏳+word; move% sign-colored;
expander reveals evidence + model_version; "how we score" modal) + `AccuracyTrendChart` (Recharts; client
computes rolling win rate from graded items oldest→newest; dashed 50 line; hidden <20 graded).

### M9i — Cross-cutting polish + verification
404 page; reduced-motion; focus rings; `<html lang>` sync; freshness captions; ensure no layout shift /
tabular-nums; final `tsc --noEmit` + `vite build` + `vitest run` all green. Update handoff/roadmap.

## Test strategy
Unit/component via vitest + Testing Library + jsdom for pure logic and stateful components (api client,
useT, formatters, market hours, sparkline, accuracy/diff/countdown logic, auth form, search behavior).
Network mocked (no real backend in the test run). Full visual + live-API verification is M10 (Caddy +
docker). Type safety (`tsc --noEmit`) and a clean production `vite build` are hard gates each slice.
