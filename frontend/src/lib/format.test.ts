import { describe, expect, it } from "vitest";

import { formatMoney, pctSign, relativeTime, signedPct } from "./format";

describe("formatMoney", () => {
  it("renders KRW as a code suffix in EN locale (§6.3.1)", () => {
    expect(formatMoney(85000, "KRW", "en")).toBe("85,000 KRW");
  });
  it("renders KRW with the won symbol in KO locale, 0 decimals", () => {
    const out = formatMoney(85000, "KRW", "ko");
    expect(out).toContain("85,000");
  });
  it("renders USD with 2 decimals", () => {
    expect(formatMoney(6.32, "USD", "en")).toBe("$6.32");
  });
});

describe("signedPct / pctSign", () => {
  it("always carries an explicit sign", () => {
    expect(signedPct(3.2)).toBe("+3.20%");
    expect(signedPct(-1.5)).toBe("-1.50%");
  });
  it("classes near-zero as neutral (§6.3.3)", () => {
    expect(pctSign(0.05)).toBe("neutral");
    expect(pctSign(2)).toBe("bull");
    expect(pctSign(-2)).toBe("bear");
    expect(pctSign(null)).toBe("neutral");
  });
});

describe("relativeTime", () => {
  const t = (k: string, p?: Record<string, string | number>) => `${k}:${p?.n ?? ""}`;
  const base = new Date("2026-06-15T00:00:00Z").getTime();
  it("buckets seconds/minutes/hours", () => {
    expect(relativeTime("2026-06-15T00:00:00Z", t, base)).toBe("time.now:");
    expect(relativeTime("2026-06-14T23:59:20Z", t, base)).toBe("time.secAgo:40");
    expect(relativeTime("2026-06-14T23:50:00Z", t, base)).toBe("time.minAgo:10");
    expect(relativeTime("2026-06-14T22:00:00Z", t, base)).toBe("time.hourAgo:2");
  });
});
