import type { Direction, Lang } from "../api/types";

const ZERO_DECIMAL = new Set(["KRW", "JPY"]);

/** Native-currency price per ui-ux §6.3.1. KRW in EN locale → "85,000 KRW" (₩ is poorly recognized
 *  by EN-locale beginners); everything else via Intl currency formatting. */
export function formatMoney(amount: number, currency: string, lang: Lang): string {
  if (currency === "KRW" && lang === "en") {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(amount)} KRW`;
  }
  const locale = lang === "ko" ? "ko-KR" : "en-US";
  const opts: Intl.NumberFormatOptions = { style: "currency", currency };
  if (ZERO_DECIMAL.has(currency)) {
    opts.minimumFractionDigits = 0;
    opts.maximumFractionDigits = 0;
  }
  try {
    return new Intl.NumberFormat(locale, opts).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}

/** Signed percent, always with an explicit +/- sign and 2 decimals (never color alone, §3/§9). */
export function signedPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

export type SignClass = "bull" | "bear" | "neutral";
/** Sign → direction class. |pct| < 0.1 reads as ≈0 (gray), per the §6.3.3 diff rule. */
export function pctSign(pct: number | null | undefined): SignClass {
  if (pct == null || Math.abs(pct) < 0.1) return "neutral";
  return pct > 0 ? "bull" : "bear";
}

export const DIR_ARROW: Record<Direction, string> = { up: "▲", down: "▼", neutral: "▬" };
export const DIR_CLASS: Record<Direction, SignClass> = { up: "bull", down: "bear", neutral: "neutral" };

/** Relative "x ago" using the i18n keys (caller supplies t). */
export function relativeTime(
  iso: string,
  t: (k: string, p?: Record<string, string | number>) => string,
  now: number = Date.now(),
): string {
  const ageMs = now - new Date(iso).getTime();
  const sec = Math.max(0, Math.floor(ageMs / 1000));
  if (sec < 5) return t("time.now");
  if (sec < 60) return t("time.secAgo", { n: sec });
  const min = Math.floor(sec / 60);
  if (min < 60) return t("time.minAgo", { n: min });
  return t("time.hourAgo", { n: Math.floor(min / 60) });
}

/** A local clock time (HH:MM) in the user's tz, from a UTC ISO string. */
export function localTime(iso: string, lang: Lang): string {
  const locale = lang === "ko" ? "ko-KR" : "en-US";
  return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}
