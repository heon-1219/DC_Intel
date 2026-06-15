# M4 — Sentiment + Market-Intel Pipeline Implementation Plan (program plan + slices)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`. M4 is large and ML-heavy, so it is split into FOUR slices, each shippable + tested: **M4a ingestion → M4b embed/cluster/credibility → M4c sentiment classifier + aggregation → M4d confirmation/anomaly/endpoint + docker smoke.** Per-slice detail plans may be written just-in-time; this doc is the program plan + the embedded research (do not lose it).

**Owner decisions (2026-06-16, AskUserQuestion):** (1) **build the real ML sentiment now** (mDeBERTa zero-shot + MiniLM clustering, local, $0); (2) **build every source for real, self-disabling**, with all required API keys/cookies documented (owner has X cookies + Reddit creds to add to `.env` later). Offline tests use fakes/cassettes; real models/sources validated via `@pytest.mark.live` + docker smoke.

**Goal:** Ingest real social + news intel for tracked stocks, clean/dedup/cluster it (MiniLM), score credibility (§6), classify sentiment (mDeBERTa zero-shot), confirm vs official news/calendar, flag anomalies, aggregate per-stock per-timeframe sentiment → `sentiment_logs`, and serve `GET /dashboard/market-intel`.

**Architecture:** Two cooperating sub-pipelines writing the shared `market_intel` table. `app/intel/` (market-intel: scrapers, clean, dedup, MiniLM embed+cluster, credibility, confirmation, anomaly, endpoint) and `app/sentiment/` (news fetchers + zero-shot classifier + aggregator → `sentiment_logs`). All tunables in `config/intel.py` (env-overridable). Models load via `transformers.pipeline` / `sentence_transformers` behind injectable interfaces so offline tests never load weights.

## Dependency + venv strategy
- New deps: `transformers`, `torch` (CPU), `sentence-transformers`, `praw` (Reddit), `selectolax` or `beautifulsoup4` (already have bs4) for KR scrapes; `httpx` (have). Optional: `twikit` for X (or thin httpx GraphQL). `langdetect` or `pycld3` for lang tag.
- **torch/transformers wheels lag Python 3.14.** First action in M4c (the ML slice): try installing on the current 3.14 venv; if wheels are missing, **rebuild the venv on Python 3.11** (`uv venv --python 3.11 backend\.venv`; pre-approved in handoff) to match the Docker runtime (`python:3.11-slim`). M4a/M4b (no torch) can proceed on 3.14; do the switch before M4c. Re-run the full suite after any venv switch.
- Models download from HuggingFace on first use (mDeBERTa ~280M / int8 ONNX ~180MB; MiniLM ~120MB). Docker: models download at container runtime first-use (or a build-time warm step — decide in M4d smoke). **Never load weights in offline tests** (inject fakes).

## Required env vars (document in `config/.env.example`; all FREE) — owner fills later
| Env var | For | Free source |
|---|---|---|
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` | Reddit (praw, OAuth script app) | reddit.com/prefs/apps |
| `STOCKTWITS_ACCESS_TOKEN` | StockTwits REST | StockTwits dev portal |
| `TWITTER_ENABLED` (default true), `TWITTER_AUTH_TOKEN`, `TWITTER_CT0` (or `TWITTER_COOKIES_FILE`) | X session-scrape cookies (NOT a password) | logged-in browser session |
| `NEWSAPI_API_KEY` | NewsAPI headlines (confirmation + news sentiment) | newsapi.org free dev tier |
| `FINNHUB_API_KEY` | Finnhub company news (have from M1) | finnhub.io |
| `SENTIMENT_CLF_MODEL` (default `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`), `SENTIMENT_CLF_MIN_CONF` (0.45), `SENTIMENT_MIN_TEXT_LEN` (10), `SENTIMENT_ACTIVE_STOCK_CAP` (50) | sentiment model config | — |
| DC Inside / Naver | NO creds (scrape; identifiable UA, robots.txt, 2–5s spacing) | — |

Every source SELF-DISABLES with a warning when its creds are absent (like M3 FRED/Finnhub).

---
## RESEARCHED SPEC FACTS (verbatim — the implementation contract; source: digests of market-intel-pipeline.md + sentiment-pipeline.md)

### Credibility (market-intel §6) — `app/intel/credibility.py`
```
credibility = round(0.30·S + 0.30·A + 0.25·C + 0.15·E)
if cluster.coordinated: credibility = min(credibility, 20)
clamp [0,100]
```
- **S** source tier: T1=90, T2=70, T3=50, T4=30 (DC/Naver default T4). News outlets: whitelist majors (Reuters/Bloomberg/Yonhap/Maeil) → 90, else 70.
- **A** author accuracy (Laplace): `A = 100·(confirmed+1)/(resolved+2)`; unknown author → 50. (resolved = author's items >48h old; confirmed = those with confirmed=1.)
- **C** corroboration: `C = min(100, 25·(n−1))`, n = distinct (source,author_handle) in cluster.
- **E** age+engagement: `age_part=min(1, age_days/365)`; `engagement_part=min(1, log10(1+engagement)/5)`; `E=round(50·age_part+50·engagement_part)`; **E=25 if no profile data**.
- **Oracle:** S=70,A=40,C=75,E=91 → 0.30·70+0.30·40+0.25·75+0.15·91 = 65.4 → **65**. News example: round(0.30·70+0.30·50+0.25·50+0.15·25)=**52**. A=100·(3+1)/(8+2)=**40**. C=25·3=**75**.
- Bands: 75–100 High / 50–74 Moderate / 25–49 Low / 0–24 Very low. Coordinated cap=20.

### Dedup/cluster (market-intel §4.3–§5.2) — `app/intel/embed.py`, `cluster.py`, `dedup.py`
- MiniLM `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-d, multilingual, CPU. Vectors in Redis `intel:emb:{id}` (384×float32 bytes, TTL 48h).
- Exact dup: SHA-256 of lowercased punctuation-stripped text → Redis set `intel:hash:{sha}` TTL48h → drop.
- Same-author near-dup: cosine ≥ **0.97** vs author's last-48h items → drop.
- Cross-author copypasta: same hash from ≥3 distinct authors within 30min → keep one, cluster `coordinated=true`.
- Cluster join: greedy centroid (same stock_id / exchange bucket if NULL, active ≤48h), join if cosine ≥ **0.80**, else new cluster. `cluster_id = "cl_"+uuid4().hex[:12]`. Cluster meta in Redis hash `intel:cluster:{cid}` (centroid, stock_id, first_posted_at, item_count, distinct_authors, coordinated, confirmed_at/url/source, anomaly_id).

### Confirmation (market-intel §8) — `app/intel/confirm.py` job `intel_confirmation_match` */10min
- Per active unconfirmed cluster: candidate = Finnhub company news (or general if stock_id NULL) + NewsAPI + same-day high-impact `economic_events`, window `[first_posted−30min, now]`. Match iff cosine(centroid, news_emb) ≥ **0.70** AND entity guard (same ticker or ≥1 shared entity token). On match: `UPDATE market_intel SET confirmed=1 WHERE cluster_id=?` + cluster Redis confirmed_at/url/source. 48h window → else permanently unconfirmed.

### Anomaly (market-intel §9) — `app/intel/anomaly.py` job `intel_anomaly_scan` */5min (market hours)
Trigger when ALL: (1) |Δprice over 30min| ≥ 3.0% (M1 Redis price cache); (2) no high-impact `economic_events` for stock's country ±60min (M3); (3) no Finnhub news last 60min; (4) not earnings day (M3); (5) cooldown 120min unless move ≥2× prior. On trigger: Redis `intel:anomaly:{sym}:{exch}:{epoch}` TTL7d; rank clusters `max_cred × exp(−hours_since_first/24) × (1.25 if sentiment matches dir else 0.80)`, exclude coordinated, pin top 3.

### Sentiment classifier (sentiment §5) — `app/sentiment/classify.py`
- `pipeline("zero-shot-classification", model="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", device=-1)`. LABELS=`["bullish","bearish","neutral"]`. HYPOTHESIS=`"The author of this post is {} about this stock's price."`, `multi_label=False`. Top label+score. If score < **0.45** → label `neutral` (keep the score). dir: bullish+1/bearish−1/neutral0. Cache Redis `sentiment:clf:{sha1(normtext)}` TTL7d.
- Normalize (order): NFC; fullwidth→halfwidth; strip URLs+@mentions (keep cashtags/hashtags); collapse ws + truncate 512 tok; keep emoji; drop <10 chars.
- StockTwits weak label (§5.4): if author Bull/Bear tag present and AGREES with model → use tag, conf `max(0.75, model_conf)`; disagree → use model.

### Aggregation (sentiment §7) — `app/sentiment/aggregate.py` job `aggregate_sentiment` */10min+2
- Item score `s_i = dir_i · conf_i · 100` (neutral=0 but stays in denom + count).
- `S(tf) = Σ(w_i·s_i)/Σw_i`, `w_i = (credibility_score_i/100)·0.5^(age_hours/half_life_tf)`, items posted ≥ now−lookback_tf.
- Per-timeframe constants (CODE, not env): 1h:(hl30m,lb2h,N5) · 5h:(2h,8h,8) · 24h:(6h,24h,10) · 2d:(12h,48h,12) · 3d:(18h,72h,12) · 5d:(24h,120h,15).
- Headline `aggregate_sentiment_score` = 24h score, 1 decimal; null if 0 items. `low_confidence:true` if item_count<N. `source_breakdown_json` (schema_version 1): `{computed_at, classifier, timeframe_scores{tf:{score,item_count,low_confidence}}, item_counts_by_source, coverage{...}, top_contributors[≤5 by weight over 24h]}`.
- **Oracle (Samsung 24h, hl6h):** decays 0.891/0.707/0.944/0.561/0.500/0.891 → S(24h)=70.6/2.281 = **+31.0**, item_count 6<10 → low_confidence true.

### Ownership split (do NOT double-implement)
- `app/intel/` owns: scrapers (reddit/stocktwits/twitter/dcinside/naver), clean+ticker-map, dedup+cluster, credibility, confirmation, anomaly, daily author-stats + retention, `GET /dashboard/market-intel`.
- `app/sentiment/` owns: news fetchers (finnhub/newsapi), classifier, aggregator → `sentiment_logs`. Both write `market_intel`.

### `market_intel` columns (schema.md): id, stock_id(NULL=market-wide), source(reddit|stocktwits|dcinside|naver|twitter|finnhub|newsapi), author_handle, url, content_snippet(≤500), posted_at, credibility_score(0-100), sentiment(bullish|bearish|neutral|NULL), sentiment_confidence(0-1), confirmed(0/1), cluster_id(cl_+12hex), created_at. Retention 90d. lang recomputed at render (≥30% Hangul → ko).

### `GET /dashboard/market-intel` (§12): params stock, lang(ko|en), limit(1-50,20), min_credibility(0-100,25), only_anomalies(bool). Cache 60s. Top-level `{as_of, lang, anomalies[], clusters[]}`. Cluster: cluster_id, stock|null, status(CONFIRMED iff any item confirmed), badge{label,style(confirmed|speculation),disclaimer} (blue/amber, NEVER green/red), sentiment, sentiment_confidence, item_count, distinct_authors, max_credibility, credibility_band, coordinated_warning, lead_time_minutes, timeline[], items[≤3 by cred], confirm_url. Auth optional (anonymous fine; no per-user state needed here).

### Jobs registry (add to scheduler): intel_scrape_reddit(5m), intel_scrape_stocktwits(5m+2), scrape_kr_communities(10m), intel_scrape_twitter(10m), intel_confirmation_match(10m), intel_anomaly_scan(5m), intel_author_stats(daily 03:00 KST=18:00 UTC prev), intel_retention(daily 03:30 KST), fetch_finnhub_news(10m), fetch_newsapi(hourly), aggregate_sentiment(10m+2). All max_instances=1, coalesce=True.

---
## Slice breakdown

### M4a — Ingestion (no heavy ML; build on 3.14)
**Delivers:** `config/intel.py` (all tunables) + `.env.example` keys; `app/intel/models.py` (`RawIntel`); `app/intel/fetchers/base.py` (`SourceFetcher` protocol + health); the 5 fetchers (reddit/stocktwits/twitter/dcinside/naver — self-disabling, cassette+live tested); `app/intel/normalize.py` (6-step clean + lang) + `app/intel/entities.py` (ticker/cashtag → stock_id); `app/intel/dedup.py` (exact SHA-256 hash dedup only — embedding near-dup is M4b); `app/db/repositories/market_intel.py` (insert + queries); deps praw + langdetect. **Exit:** real posts ingest into `market_intel` (exact-deduped), tested with cassettes; live-marked tests per reachable source.

### M4b — Embed + cluster + credibility (no torch; sentence-transformers is the only ML dep, loadable on 3.11 — gate to M4c if 3.14 wheels missing)
**Delivers:** `app/intel/embed.py` (MiniLM behind `Embedder` interface + Redis vector cache), `app/intel/cluster.py` (greedy centroid, cluster_id, coordinated detection, near-dup 0.97), `app/intel/credibility.py` (S/A/C/E — oracle-tested), `intel_author_stats` + `intel_retention` jobs. **Exit:** credibility reproduces the §6 oracles; clustering assigns cluster_id; embeddings cached. (NOTE: sentence-transformers pulls torch → may force the 3.11 switch here; if so, do the venv switch at the start of M4b.)

### M4c — Sentiment classifier + aggregation (heavy ML; do venv→3.11 first if needed)
**Delivers:** `app/sentiment/classify.py` (zero-shot wrapper behind `Classifier` interface + Redis cache + weak-label rule), `app/sentiment/normalize.py`, `app/sentiment/aggregate.py` (the §7 formula — oracle-tested vs Samsung +31.0), `app/sentiment/fetchers/` (finnhub_news, newsapi), `aggregate_sentiment` + `fetch_finnhub_news` + `fetch_newsapi` jobs, `sentiment_logs` repo. **Exit:** aggregation reproduces the §7.3 oracle; classifier fake-injectable; real model behind a live test.

### M4d — Confirmation + anomaly + endpoint + smoke
**Delivers:** `app/intel/confirm.py` + `intel_confirmation_match`, `app/intel/anomaly.py` + `intel_anomaly_scan`, `GET /dashboard/market-intel` (router), all scheduler/lifespan wiring, full-M4 docker smoke. **Exit:** endpoint serves clusters/anomalies; confirmation flips confirmed; anomaly gated by M1 price + M3 events; docker smoke ingests + serves real intel.

## Deferrals / notes
- Optional ONNX int8 quantization of mDeBERTa (perf) — deferred; run the plain HF pipeline in v1.
- Korean-template A/B for sentiment — deferred (English hypothesis for all langs per spec).
- Per-user anything — none needed here (endpoint is effectively anonymous; auth optional).
- Resolve doc discrepancies: subreddit list + StockTwits cadence → use `config/intel.py` values as source of truth; the §7.1 "-52" prose is loose — the formula `s_i=dir·conf·100` + §7.3 table are authoritative.

## Self-review
- Coverage: scrapers (M4a) · clean/dedup (M4a) · embed/cluster/credibility (M4b) · classifier/aggregate/news (M4c) · confirm/anomaly/endpoint (M4d) — every roadmap M4 deliverable mapped. ✓
- REAL-data: cassettes + live tests + docker smoke; offline never loads weights. ✓
- Every tunable from config; env vars documented + self-disabling. ✓
- Oracles captured for credibility + aggregation (the two formula-heavy, bug-prone cores). ✓
