import { useEffect, useState } from "react";

import type { MarketState } from "../api/types";

const TZ: Record<string, string> = {
  KRX: "Asia/Seoul",
  NASDAQ: "America/New_York",
  NYSE: "America/New_York",
  AMEX: "America/New_York",
};

function partsInTz(now: Date, tz: string): { mins: number; weekend: boolean } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  let hour = parseInt(get("hour"), 10);
  if (hour === 24) hour = 0;
  const minute = parseInt(get("minute"), 10);
  const wd = get("weekday");
  return { mins: hour * 60 + minute, weekend: wd === "Sat" || wd === "Sun" };
}

/** Client-side session (ui-ux §10): KRX 09:00–15:30 KST; US 09:30–16:00 ET (+pre 04:00/post 20:00).
 *  Weekly only (no holidays — a server concern). The server's own market_state wins when present. */
export function clientMarketState(exchange: string, now: Date = new Date()): MarketState {
  const tz = TZ[exchange];
  if (!tz) return "closed";
  const { mins, weekend } = partsInTz(now, tz);
  if (weekend) return "closed";
  if (exchange === "KRX") return mins >= 540 && mins <= 930 ? "open" : "closed"; // 09:00–15:30
  // US
  if (mins >= 570 && mins <= 960) return "open"; // 09:30–16:00
  if (mins >= 240 && mins < 570) return "pre"; // 04:00–09:30
  if (mins > 960 && mins <= 1200) return "post"; // 16:00–20:00
  return "closed";
}

/** Reactive market state; recomputes each minute. A server-supplied state always wins. */
export function useMarketHours(exchange: string, serverState?: MarketState | null): MarketState {
  const [state, setState] = useState<MarketState>(() => clientMarketState(exchange));
  useEffect(() => {
    if (serverState) return;
    setState(clientMarketState(exchange));
    const id = setInterval(() => setState(clientMarketState(exchange)), 60_000);
    return () => clearInterval(id);
  }, [exchange, serverState]);
  return serverState ?? state;
}

export function isOpenish(state: MarketState): boolean {
  return state === "open" || state === "pre" || state === "post";
}
