import type { Query } from "@tanstack/react-query";

/** ±10% jitter so many clients don't synchronize (ui-ux §3.1). */
export function jitter(ms: number): number {
  return Math.round(ms * (0.9 + Math.random() * 0.2));
}

const MAX_BACKOFF_MS = 600_000; // 10 min cap (§3.1 failure backoff)

/** A TanStack `refetchInterval` callback: jittered base while healthy; after 3 consecutive failed
 *  polls, double per failure up to 10 min. Pair with `refetchIntervalInBackground: false` so polling
 *  pauses when the tab is hidden (Page Visibility, §3.1). */
export function pollInterval(baseMs: number) {
  return (query: Query): number => {
    const fails = query.state.fetchFailureCount;
    if (fails >= 3) return Math.min(baseMs * 2 ** (fails - 2), MAX_BACKOFF_MS);
    return jitter(baseMs);
  };
}

/** Spread into a useQuery options object for a polled widget. */
export function pollOptions(baseMs: number) {
  return { refetchInterval: pollInterval(baseMs), refetchIntervalInBackground: false } as const;
}
