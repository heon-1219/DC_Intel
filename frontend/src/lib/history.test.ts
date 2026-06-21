import { describe, expect, it } from "vitest";

import type { HistoryItem, OutcomeStatus } from "../api/types";
import { gradedCount, rollingWinRate } from "./history";

function item(status: OutcomeStatus): HistoryItem {
  return {
    prediction_id: Math.random(),
    timeframe: "24h",
    direction: "up",
    confidence: 60,
    evidence_summary_en: "",
    evidence_summary_ko: "",
    predicted_at: "2026-01-01T00:00:00Z",
    window_closes_at: "2026-01-02T00:00:00Z",
    entry_price: null,
    currency: "USD",
    model_version: "v",
    status,
    outcome: null,
  };
}

describe("history trend", () => {
  it("counts only graded items", () => {
    expect(gradedCount([item("correct"), item("pending"), item("incorrect")])).toBe(2);
  });

  it("computes cumulative win rate oldest→newest (API is newest-first)", () => {
    // newest-first: [incorrect, correct] → oldest-first: [correct, incorrect]
    const series = rollingWinRate([item("incorrect"), item("correct"), item("pending")]);
    expect(series).toEqual([
      { x: 1, rate: 100 },
      { x: 2, rate: 50 },
    ]);
  });
});
