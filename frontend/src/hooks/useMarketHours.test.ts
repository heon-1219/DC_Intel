import { describe, expect, it } from "vitest";

import { clientMarketState } from "./useMarketHours";

const at = (iso: string) => new Date(iso);

describe("clientMarketState", () => {
  it("KRX open during 09:00–15:30 KST on a weekday", () => {
    expect(clientMarketState("KRX", at("2026-06-15T02:00:00Z"))).toBe("open"); // Mon 11:00 KST
    expect(clientMarketState("KRX", at("2026-06-15T08:00:00Z"))).toBe("closed"); // 17:00 KST
  });
  it("KRX closed on weekends", () => {
    expect(clientMarketState("KRX", at("2026-06-13T02:00:00Z"))).toBe("closed"); // Sat
  });
  it("US open/pre/post/closed in ET on a weekday", () => {
    expect(clientMarketState("NASDAQ", at("2026-06-15T15:00:00Z"))).toBe("open"); // Mon 11:00 EDT
    expect(clientMarketState("NYSE", at("2026-06-15T12:00:00Z"))).toBe("pre"); // 08:00 EDT
    expect(clientMarketState("NASDAQ", at("2026-06-15T21:00:00Z"))).toBe("post"); // 17:00 EDT
    expect(clientMarketState("NASDAQ", at("2026-06-16T01:00:00Z"))).toBe("closed"); // Mon 21:00 EDT
  });
  it("unknown exchange (e.g. INDEX) is closed client-side", () => {
    expect(clientMarketState("INDEX", at("2026-06-15T02:00:00Z"))).toBe("closed");
  });
});
