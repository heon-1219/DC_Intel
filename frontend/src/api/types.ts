// Response types mirroring backend-design.md §6 + the M8 endpoints. The backend wraps every success
// in { data, meta } and every error in { error }.

export type Lang = "en" | "ko";
export type MarketState = "open" | "closed" | "pre" | "post";
export type Direction = "up" | "down" | "neutral";
export type Timeframe = "1h" | "5h" | "24h" | "2d" | "3d" | "5d";
export const TIMEFRAMES: Timeframe[] = ["1h", "5h", "24h", "2d", "3d", "5d"];

export interface Meta {
  source: string;
  data_as_of: string;
  is_stale: boolean;
  cache: string;
  request_id: string;
}
export interface Envelope<T> {
  data: T;
  meta: Meta;
}
export interface ErrorBody {
  error: { code: string; message_en: string; message_ko: string; details?: unknown; request_id: string };
}

// --- auth ---
export interface AuthUser {
  id: number;
  email: string;
  language: Lang;
}
export interface AuthData {
  user: AuthUser;
  access_token: string;
  token_type: string;
  expires_in: number;
}

// --- price ---
export interface PriceData {
  instrument: string;
  name_en: string;
  name_ko: string;
  price: number;
  currency: string;
  change: number | null;
  change_pct: number | null;
  previous_close: number | null;
  volume: number | null;
  day_high: number | null;
  day_low: number | null;
  market_state: MarketState;
}

// --- search ---
export interface SearchListing {
  instrument: string;
  symbol: string;
  exchange: string;
  board: string | null;
  currency: string;
  is_primary: boolean;
  kind: "common" | "adr";
  last_price: number | null;
  price_as_of: string | null;
  fx_rate: number | null;
  diff_vs_primary_pct: number | null;
}
export interface SearchResult {
  company_name_en: string;
  company_name_ko: string;
  listings: SearchListing[];
}
export interface SearchData {
  query: string;
  results: SearchResult[];
}

// --- trending ---
export interface TrendingCard {
  instrument: string;
  name_en: string;
  name_ko: string;
  price: number;
  currency: string;
  change_pct: number;
  volume: number | null;
  sparkline: number[];
  win_rate_pct: number | null;
  n_closed: number;
}
export interface TrendingRegion {
  region: string;
  market_state: MarketState;
  gainers: TrendingCard[];
  losers: TrendingCard[];
}
export interface TrendingData {
  regions: TrendingRegion[];
}

// --- indexes ---
export interface IndexTile {
  code: string;
  name_en: string;
  name_ko: string;
  level: number | null;
  change: number | null;
  change_pct: number | null;
  market_state: MarketState;
  sparkline: number[];
  data_as_of: string | null;
}
export interface IndexesData {
  indexes: IndexTile[];
}

// --- cross-market (prices-across-markets) ---
export interface XmktListing {
  instrument: string;
  exchange: string;
  currency: string;
  price: number | null;
  change_pct: number | null;
  adr_ratio: string | null;
  normalized_usd: number | null;
  diff_pct_vs_base: number | null;
  market_state: MarketState;
  data_as_of: string | null;
  is_stale: boolean;
}
export interface CrossMarketData {
  company_name_en: string;
  company_name_ko: string;
  base_instrument: string;
  fx_rates: { USDKRW: number | null; as_of: string };
  listings: XmktListing[];
  note_en: string;
  note_ko: string;
}

// --- economic calendar ---
export interface CalendarEvent {
  id: number;
  event_type: string;
  title_en: string;
  title_ko: string;
  plain_summary_en: string | null;
  plain_summary_ko: string | null;
  country: string;
  impact_level: "high" | "medium" | "low";
  impact_source: string;
  scheduled_at_utc: string;
  status: string;
  actual_vs_forecast: unknown;
  countdown_seconds: number | null;
  affects_your_stocks: boolean | null;
  match_level: string | null;
  matched_symbols: string[];
}
export interface CalendarData {
  server_time_utc: string;
  range: { from_utc: string; to_utc: string };
  last_synced_at_utc: string | null;
  data_stale: boolean;
  events: CalendarEvent[];
}

// --- market intel (feed.build_clusters shape) ---
export type Sentiment = "bullish" | "bearish" | "neutral";
export interface IntelBadge {
  label: string;
  style: "confirmed" | "speculation";
  disclaimer: string;
}
export interface IntelItem {
  id: number;
  source: string;
  author_handle: string | null;
  url: string | null;
  content_snippet: string;
  lang: string;
  posted_at: string;
  credibility_score: number;
  sentiment: Sentiment;
  sentiment_confidence: number;
  confirmed: boolean;
}
export interface IntelStock {
  symbol: string;
  exchange: string;
  name_en: string;
  name_ko: string;
}
export interface IntelCluster {
  cluster_id: string;
  status: "CONFIRMED" | "UNCONFIRMED";
  badge: IntelBadge;
  sentiment: Sentiment;
  sentiment_confidence: number;
  item_count: number;
  distinct_authors: number;
  max_credibility: number;
  credibility_band: string;
  coordinated_warning: boolean;
  lead_time_minutes: number | null;
  timeline: { event: string; at: string }[];
  items: IntelItem[];
  confirm_url: string | null;
  stock: IntelStock | null;
}
export interface IntelAnomaly {
  // Shape written by backend/app/intel/anomaly.py.
  direction?: "up" | "down";
  change_pct?: number;
  window_minutes?: number;
  detected_at?: string;
  stock?: { symbol: string; exchange: string };
  [k: string]: unknown;
}
export interface MarketIntelData {
  as_of: string;
  lang: Lang;
  anomalies: IntelAnomaly[];
  clusters: IntelCluster[];
}

// --- whisper EPS (AIWCE corroboration) ---
// status bands (whisper_config): corroborated ≥75, tentative 55–75, no_reliable_whisper <55.
// `null` status = no row computed yet (the backend returns 200 with empty fields, never 404).
export type WhisperStatus = "corroborated" | "tentative" | "no_reliable_whisper";
export interface WhisperData {
  instrument: string;
  status: WhisperStatus | null;
  whisper_value: number | null;
  confidence: number | null; // 0..100
  anchor: number | null; // official consensus EPS
  surprise_vs_anchor: number | null; // whisper − anchor
  earnings_date: string | null; // ISO date (YYYY-MM-DD)
  n_inliers: number;
  n_outliers_rejected: number;
  n_distinct_families: number;
  contributing_families: string[];
  inlier_dispersion: number | null;
  factors: Record<string, unknown>;
  abstain_reason: string | null;
  rounds_used: number;
  computed_at: string | null;
}

// --- predict ---
export interface EvidenceItem {
  kind: "technical" | "sentiment" | "calendar" | string;
  text_en: string;
  text_ko: string;
  contribution_pct: number;
}
export interface PredictData {
  prediction_id: number;
  instrument: string;
  name_en: string;
  name_ko: string;
  timeframe: Timeframe;
  direction: Direction;
  confidence: number;
  evidence: EvidenceItem[];
  evidence_summary_en: string;
  evidence_summary_ko: string;
  predicted_at: string;
  window_closes_at: string;
  entry_price: number | null;
  currency: string;
  model_version: string;
  neutral_rule_applied: boolean;
  confidence_capped: boolean;
  data_staleness: { any_stale: boolean };
  high_impact_events: unknown[];
}

// --- accuracy ---
export interface DirectionalStats {
  predictions: number;
  wins: number;
  losses?: number;
  win_rate_pct: number | null;
}
export interface AccuracyByTimeframe {
  timeframe: Timeframe;
  graded: number;
  exact_accuracy_pct: number | null;
  directional: DirectionalStats;
}
export interface AccuracyData {
  instrument: string;
  window: string;
  graded_total: number;
  pending: number;
  exact_accuracy_pct: number | null;
  directional: DirectionalStats;
  neutral_predictions: number;
  low_sample: boolean;
  by_timeframe: AccuracyByTimeframe[];
}

// --- history ---
export type OutcomeStatus = "pending" | "correct" | "incorrect";
export interface HistoryOutcome {
  realized_direction: Direction;
  exit_price: number | null;
  move_pct: number | null;
  graded_at: string;
}
export interface HistoryItem {
  prediction_id: number;
  timeframe: Timeframe;
  direction: Direction;
  confidence: number;
  evidence_summary_en: string;
  evidence_summary_ko: string;
  predicted_at: string;
  window_closes_at: string;
  entry_price: number | null;
  currency: string;
  model_version: string;
  status: OutcomeStatus;
  outcome: HistoryOutcome | null;
}
export interface HistoryData {
  instrument: string;
  total: number;
  items: HistoryItem[];
}
