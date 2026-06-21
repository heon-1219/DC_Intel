import { describe, expect, it } from "vitest";

import { jitter, pollInterval } from "./usePolling";

const q = (fails: number) => ({ state: { fetchFailureCount: fails } });

describe("polling", () => {
  it("jitter stays within ±10%", () => {
    for (let i = 0; i < 200; i++) {
      const v = jitter(60_000);
      expect(v).toBeGreaterThanOrEqual(54_000);
      expect(v).toBeLessThanOrEqual(66_000);
    }
  });

  it("uses jittered base while healthy", () => {
    const fn = pollInterval(60_000);
    const v = fn(q(0));
    expect(v).toBeGreaterThanOrEqual(54_000);
    expect(v).toBeLessThanOrEqual(66_000);
  });

  it("backs off after 3 consecutive failures, capped at 10 min", () => {
    const fn = pollInterval(60_000);
    expect(fn(q(3))).toBe(120_000); // 60s * 2^1
    expect(fn(q(4))).toBe(240_000); // 60s * 2^2
    expect(fn(q(20))).toBe(600_000); // capped
  });
});
