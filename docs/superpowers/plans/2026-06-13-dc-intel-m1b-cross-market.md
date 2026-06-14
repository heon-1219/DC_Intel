# M1b — Cross-Market Prices + FX Plan (lean)

> Slice M1b of milestone M1. Builds on M1a (live `px:quote:*` cache). Executed inline under
> milestone cadence (no separate review), so this is a design + task outline; full code lands
> in the files via TDD. Default tests offline (fakes/fakeredis); real upstream `@pytest.mark.live`.

**Goal:** `GET /stocks/{symbol}:{exchange}/prices-across-markets` — every listing of the same
company, normalized to a per-underlying-share **USD** basis (ADR ratio × FX) with `diff_pct_vs_base`,
per `backend-design.md` §6.6. Also fix the `/price` `name_en/ko` placeholders from M1a.

**Key decisions**
- **FX source = yfinance `KRW=X`** (USD→KRW), consistent with our primary provider, free, no key.
  Only USDKRW is needed in v1 (cross-market is KRX↔US-ADR = KRW↔USD). Cached at `px:fx:USDKRW`, 5-min TTL.
- Normalization: `normalized_usd = price_in_usd / shares_per_adr`. KRW listing → `price / USDKRW`.
  USD ADR → `price` (already USD) but represents `adr_ratio` underlying shares, so per-underlying-share
  USD = `price / adr_ratio`. `diff_pct_vs_base = (listing_norm - base_norm)/base_norm * 100`.
- A listing with no fresh `px:quote` → its row shows `price: null`, `diff_pct_vs_base: null` (no fabrication).

**Tasks (TDD, commit each):**

1. **FX provider + cache helper.** `app/providers/fx_provider.py` `FxProvider.fetch_usdkrw()`
   (yfinance `KRW=X` fast_info `last_price`, lazy import, errors→ProviderError). `app/services/fx.py`
   `get_usdkrw(redis, fx_provider)` — read `px:fx:USDKRW`; on miss fetch + `setex 300`; returns float|None.
   Tests: provider error-wrap (monkeypatch) + `@live`; cache hit/miss with fakeredis + fake fx.

2. **Repo: names on StockRef + company listings.** Add `company_name`, `company_name_ko` to `StockRef`
   (trailing fields, default None — positional constructions unaffected) and to `_COLS`/`_row_to_ref`.
   Add `get_company_listings(con, symbol, exchange)` → resolves the base row, then returns all rows
   sharing `company_group` (or just the base if `company_group` is NULL) as a list of
   `Listing(instrument, symbol, exchange, currency, adr_ratio)` + the base company names. Tests against
   the seed (SK Telecom-style grouping isn't in the seed, so add a grouped pair OR test single-listing +
   group via a temp insert). NOTE: seed has `company_group` set (e.g. samsung-electronics) but only one
   listing each; PKX has group `posco-holdings` (single tracked listing). Test single-listing path with
   005930, and the multi-listing path by inserting a second listing in the test DB.

3. **Cross-market service.** `app/services/xmkt.py` `build_cross_market(base_symbol, base_exchange,
   listings, names, redis, usdkrw)` → for each listing read `px:quote`, compute `normalized_usd`
   (KRW→USD via usdkrw; ADR via adr_ratio), `diff_pct_vs_base` vs the base listing, `is_stale` per
   listing; returns the `backend-design.md` §6.6 `data` dict (company names, base_instrument, fx_rates,
   listings[], bilingual note). Tests: fakeredis with pre-set quotes for 2 listings + a known usdkrw →
   assert normalized_usd + diff_pct; missing-quote listing → price/diff null.

4. **Endpoint + `/price` name fix.** `GET /stocks/{i}/prices-across-markets` in `routers/stocks.py`
   (parse → resolve (404) → get_company_listings → get_usdkrw → build_cross_market → `{data,meta}`
   envelope; `px:xmkt:*` 60-s cache optional in v1, compute-on-request is fine). Update `/price` to use
   `ref.company_name`/`ref.company_name_ko`. Tests: app_client + seeded + pre-set fake quotes → 200 shape;
   404 unknown; 400 bad instrument; `/price` now returns real names.

**Exit:** `/prices-across-markets` returns the §6.6 shape from real cached quotes + FX; `/price` shows real
names; offline suite green; FX live test passes. Then the combined M1 docker smoke (M1a `/price` + M1b).
