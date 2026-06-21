import { describe, expect, it } from "vitest";

import { sparklinePath } from "./Sparkline";

describe("sparklinePath", () => {
  it("is empty for fewer than 2 points", () => {
    expect(sparklinePath([], 100, 20)).toBe("");
    expect(sparklinePath([5], 100, 20)).toBe("");
  });

  it("maps min to the bottom and max to the top, padded", () => {
    // points [0,10], width 100, height 20, pad 2 → first at bottom (y=18), last at top (y=2)
    expect(sparklinePath([0, 10], 100, 20)).toBe("M2.00,18.00 L98.00,2.00");
  });

  it("produces one segment per point", () => {
    const path = sparklinePath([1, 2, 3, 4], 100, 20);
    expect((path.match(/[ML]/g) ?? []).length).toBe(4);
  });
});
