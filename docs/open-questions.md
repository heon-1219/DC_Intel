# DC Intel — Decisions Log (v1)

**Status:** all open questions resolved by the owner's four standards (2026-06-13). Docs updated to match. This is now the decision record, not an open list.

**Governing standards (owner, binding):**
1. **Completely free** — no paid APIs, no paid hosting, no paid tiers in v1.
2. **International standards** — green=up/red=down, international date/number conventions; UI/UX must be clean and detail-perfect (alignment, spacing, no layout shift, no clipping — see `ui-ux.md` P9).
3. **Domain & alert channel skippable** — local-first; sensible local defaults for now.
4. **Real data always** — live data from real sources; no mock/synthetic/seeded fixtures anywhere (training, prices, sentiment, win rates).

Each item: **Decision** · why · doc status.

---

## A. Budget — all resolved to $0

| # | Question | Decision | Why | Doc |
|---|---|---|---|---|
| A1 | Economic-calendar source | **Investing.com scrape (primary) + free official composite fallback** (FRED dates + Finnhub calendars + static FOMC/BOK seeds). Trading Economics = not used. | Only $0 option covering US+KR (std 1). | already set in `data-sources.md`, `economic-calendar.md` |
| A2 | Twitter/X | **ON in v1 via logged-in session scraping** (`TWITTER_ENABLED=true`), **personal-use**. Free ($0) — reuses a dedicated account's session cookies (`TWITTER_AUTH_TOKEN`+`TWITTER_CT0`), no paid API. Polite low volume, breaker cooldown on lock; **no proxy/fingerprint/multi-account evasion**. Accepted risks (informed): breaches X ToS, the account may be suspended, the internal API breaks periodically → treat X as a **best-effort, may-disappear** source; the pipeline degrades gracefully without it. Revisit (→ paid Basic API) only if DC Intel is ever distributed/commercialized. | std 1 (free) + std 4 (real data); owner chose scraping over the paid API. ⚠️ ToS/account risk consciously accepted. | **updated** `data-sources.md` §4.1, `market-intel-pipeline.md` §3.1/§14, `sentiment-pipeline.md` §9.3, `deployment-architecture.md` §3.1/§7.2, `schema.md`, `prediction-model.md`, `architecture.html` |
| A3 | NewsAPI tier | **Free tier only; never pay.** Accept ~24 h delay (feeds 2d/3d/5d windows); Finnhub is the real-time news source. Its non-commercial license is fine for local/personal v1; if the product ever goes public-commercial, **drop NewsAPI rather than pay**. | std 1. | `data-sources.md` (already free; license caveat noted) |
| A4 | Hosting + model RAM | **Local-first, $0.** Run the docker-compose stack on `localhost`; run the **full** mDeBERTa sentiment model locally. Paid Seoul VM = **out of scope**. Optional free-cloud demo path documented (GCP free e2-micro US + MiniLM model = a feature-cut), not adopted. | std 1 + std 3. | **updated** `deployment-architecture.md` §5/§1/§7.2/§8.3/§11, `sentiment-pipeline.md` §5.1 |
| A5 | KRX quote fallback | **pykrx** (free, no brokerage account). | std 1. | already set in `data-sources.md` |

## B. Scope

| # | Question | Decision | Doc |
|---|---|---|---|
| B1 | Training universe | **~750 symbols** (KOSPI 200 + S&P 500 + top ~50 ADRs), trained on **real** 6–12-mo history (std 4). yfinance is free (std 1). | `prediction-model.md` (confirmed) |
| B2 | Trending regions | **KR/US tabs only** (no Global) in v1. | `ui-ux.md`/`backend-design.md` (confirmed) |
| B3 | `/predict` auth | **Login required** (every prediction is logged → powers `/history` + accuracy). | `backend-design.md` (confirmed) |
| B4 | Refresh tokens | **24 h JWT, no refresh in v1**; refresh flow deferred to v1.1. | `deployment-architecture.md` (confirmed) |
| B5 | JWT claims | **`{sub, iat, exp}`** (email excluded). | `backend-design.md` §3.2 (confirmed) |

> Already settled in the docs (not re-opened): off-hours predictions are **allowed** (clock starts next session open); neutral dead-bands fixed at ±0.15/0.30/0.40/0.50/0.60/0.75 %.

## C. Legal / compliance

| # | Question | Decision | Why | Doc |
|---|---|---|---|---|
| C1 | Korean community scraping (DC Inside / Naver) | **Approved for v1, with safeguards:** public pages only, respect `robots.txt`, conservative rate limits (the §4.4 cadence), source-attributed, honor takedown requests, no login-walled content. | std 4 (it's the only **free, real** KR retail signal) + std 1. ⚠️ Residual legal risk consciously accepted — flip to Reddit/StockTwits-only if you'd rather not carry it. | `data-sources.md` §4.4, `market-intel-pipeline.md` (already v1) |
| C2 | Pump/coordinated clusters | **Warn-and-hide-by-default** (capped credibility 20, shown only if the user lowers the filter, with a "possible coordinated promotion" label). | Honest + safe. | `market-intel-pipeline.md` (confirmed) |
| C3 | Public win rates | **Public from day one**, with the `low_sample`/"collecting data" state below 20 graded. | std 4 + honesty is the product. | `backend-design.md`/`win-loss-tracking.md` (confirmed) |

## D. Product / UX

| # | Question | Decision | Doc |
|---|---|---|---|
| D1 | Market colors | **International: green = up, red = down, gray = neutral** — both locales. | std 2 · `ui-ux.md` P2 (confirmed) |
| D2 | Mega-cap high-impact earnings list | **Confirmed:** AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, AVGO, 005930 (Samsung), 000660 (SK hynix). Extensible later. | `economic-calendar.md` (confirmed) |
| D3 | "Stocks you follow" lookback | **14 days** (from recent `predictions`; no watchlist table in v1). | `economic-calendar.md` (confirmed) |
| D4 | Rule-downgraded neutral confidence | **Show it** (honest "no clear signal", e.g. "neutral, 21%"). | `prediction-model.md`/`ui-ux.md` (confirmed) |
| D5 | Timeframe that fails the 52 % gate | **Disabled-with-note** ("still in testing") — all six buttons stay present so the selector alignment is consistent (std 2). | `prediction-model.md`/`ui-ux.md` (confirmed) |
| D6 | Min sample before a win rate | **20 graded** (`MIN_ACCURACY_SAMPLE = 20`). | `ui-ux.md`/`win-loss-tracking.md` (confirmed) |
| D7 | KR events vs US-listed Korean ADRs | **Accept v1 as-is** (KR events don't flag NYSE/NASDAQ ADRs); refine later if ADR accuracy looks event-driven. | `win-loss-tracking.md` (confirmed) |

## E. Operational config — local-first defaults (std 3)

| # | Question | Decision | Doc |
|---|---|---|---|
| E1 | Production domain | **`localhost`** (plain HTTP, no DNS/TLS in v1). Real domain only for the optional cloud demo. | **updated** `deployment-architecture.md` §7.2/§4/§11 |
| E2 | Alert channel | **Local: `logs/alerts.log` (structured) + console.** No webhook in v1; `ALERT_WEBHOOK_URL` is optional. | **updated** `deployment-architecture.md` §8.3/§7.2 |
| E3 | `listing_price_usd` meaning | **IPO/first-listing reference price in USD** (display-only; live prices live in Redis). | `schema.md` (confirmed) |
| E4 | Data retention | **Confirmed defaults:** intraday 5m/15m 14 d, 1h 90 d, 1d 2 y, `sentiment_logs` 90 d, `market_intel` 90 d; `predictions`/`prediction_outcomes` forever. (~3–6 GB local disk.) | `schema.md` (confirmed) |

## F. Tuning constants — calibrate against real data (std 4)

No pre-build decision; the team validates these after the first real backfill:
- Neutral dead-band class balance — confirm "neutral" lands ~20–40 % of labels per timeframe after the first labeling pass (re-tuning is a breaking label change → settle before the first public model). (`win-loss-tracking.md`)
- First-bar gap guard `0.5 × Bollinger σ` (`technical-indicators.md` §9.2).
- Cold-symbol first-prediction latency target `< 1.5 s` (`technical-indicators.md`).
- Staleness confidence cap `65` (`prediction-model.md`).
- **Known-trader list + Tier-1 outlet whitelist** — owner-maintained config files (`config/known_traders.yml`, `config/outlets.yml`); seed a small starter set, grow over time. (`sentiment-pipeline.md` §11)

---

## Global note — "real data always" (std 4)

No part of v1 uses mock, synthetic, or hand-seeded market data: prices/volume/fundamentals come live from yfinance (pykrx/Finnhub fallback), macro from FRED, calendar from the Investing.com scrape/composite, sentiment from real Reddit/StockTwits/KR-community/news text, and models train on real historical bars. The only seeded file is the **stock universe list** (reference metadata: symbol/exchange/names/tickers), which is configuration, not market data. Win rates shown to users are real outcomes only — the "collecting data" state covers the cold-start period rather than any placeholder number.
