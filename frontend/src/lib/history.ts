import type { HistoryItem } from "../api/types";

function gradedOldestFirst(items: HistoryItem[]): HistoryItem[] {
  // API returns newest-first; the trend reads oldest→newest.
  return items.filter((i) => i.status === "correct" || i.status === "incorrect").slice().reverse();
}

export function gradedCount(items: HistoryItem[]): number {
  return items.filter((i) => i.status === "correct" || i.status === "incorrect").length;
}

/** Client-side rolling (cumulative) win rate over the user's graded predictions (§7.4.7). */
export function rollingWinRate(items: HistoryItem[]): { x: number; rate: number }[] {
  let wins = 0;
  return gradedOldestFirst(items).map((it, i) => {
    if (it.status === "correct") wins += 1;
    return { x: i + 1, rate: Math.round((wins / (i + 1)) * 100) };
  });
}
