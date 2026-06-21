// Fetch wrapper: base URL, JWT header, {data,meta} unwrap, typed ApiError, 401 → clear+redirect.
import type {
  AccuracyData,
  AuthData,
  CalendarData,
  CrossMarketData,
  Envelope,
  HistoryData,
  IndexesData,
  Lang,
  MarketIntelData,
  PredictData,
  PriceData,
  SearchData,
  Timeframe,
  TrendingData,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const TOKEN_KEY = "dc_intel_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public messageEn: string,
    public messageKo: string,
    public details?: unknown,
  ) {
    super(`${code} (${status})`);
    this.name = "ApiError";
  }
  localized(lang: Lang): string {
    return lang === "ko" ? this.messageKo || this.messageEn : this.messageEn;
  }
}

let onUnauthorized: (() => void) | null = null;
/** Wired by AuthProvider so any 401 clears the session and redirects to login. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

interface ReqOpts {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: ReqOpts = {}): Promise<Envelope<T>> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    /* empty / non-JSON body */
  }
  const err = (json as { error?: ErrorShape } | null)?.error;

  if (res.status === 401) {
    setToken(null);
    onUnauthorized?.();
    throw new ApiError(401, err?.code ?? "UNAUTHORIZED", err?.message_en ?? "Sign in to continue.",
      err?.message_ko ?? "로그인이 필요해요.", err?.details);
  }
  if (!res.ok || err) {
    throw new ApiError(res.status, err?.code ?? "ERROR", err?.message_en ?? "Request failed.",
      err?.message_ko ?? "요청에 실패했어요.", err?.details);
  }
  return json as Envelope<T>;
}
interface ErrorShape {
  code: string;
  message_en: string;
  message_ko: string;
  details?: unknown;
}

const enc = encodeURIComponent;

export const api = {
  // auth
  login: (email: string, password: string) =>
    request<AuthData>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, language: Lang) =>
    request<AuthData>("/auth/register", { method: "POST", body: { email, password, language } }),

  // stock
  price: (listing: string, signal?: AbortSignal) =>
    request<PriceData>(`/stocks/${listing}/price`, { signal }),
  predict: (listing: string, timeframe: Timeframe, signal?: AbortSignal) =>
    request<PredictData>(`/stocks/${listing}/predict?timeframe=${timeframe}`, { signal }),
  pricesAcrossMarkets: (listing: string, signal?: AbortSignal) =>
    request<CrossMarketData>(`/stocks/${listing}/prices-across-markets`, { signal }),
  accuracy: (listing: string, signal?: AbortSignal) =>
    request<AccuracyData>(`/stocks/${listing}/accuracy`, { signal }),
  history: (listing: string, limit = 30, signal?: AbortSignal) =>
    request<HistoryData>(`/stocks/${listing}/history?limit=${limit}`, { signal }),
  search: (q: string, signal?: AbortSignal) =>
    request<SearchData>(`/stocks/search?q=${enc(q)}`, { signal }),

  // dashboard
  trending: (region: "kr" | "us" | "all", signal?: AbortSignal) =>
    request<TrendingData>(`/dashboard/trending?region=${region}`, { signal }),
  indexes: (signal?: AbortSignal) => request<IndexesData>("/dashboard/indexes", { signal }),
  calendar: (lang: Lang, days = 7, signal?: AbortSignal) =>
    request<CalendarData>(`/dashboard/economic-calendar?days=${days}&lang=${lang}`, { signal }),
  marketIntel: (lang: Lang, opts: { stock?: string; limit?: number } = {}, signal?: AbortSignal) => {
    const qs = new URLSearchParams({ lang, limit: String(opts.limit ?? 20) });
    if (opts.stock) qs.set("stock", opts.stock);
    return request<MarketIntelData>(`/dashboard/market-intel?${qs.toString()}`, { signal });
  },
};
