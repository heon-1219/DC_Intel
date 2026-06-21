import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, getToken, setToken, setUnauthorizedHandler } from "./client";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  });
}

afterEach(() => {
  setToken(null);
  setUnauthorizedHandler(null);
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("unwraps the {data, meta} envelope", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { data: { price: 100 }, meta: { source: "yfinance" } }));
    const res = await api.price("005930:KRX");
    expect(res.data).toEqual({ price: 100 });
    expect(res.meta.source).toBe("yfinance");
  });

  it("throws a typed ApiError on an {error} body", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(404, { error: { code: "SYMBOL_NOT_FOUND", message_en: "Unknown", message_ko: "없음" } }),
    );
    await expect(api.price("ZZZZ:KRX")).rejects.toMatchObject({ code: "SYMBOL_NOT_FOUND", status: 404 });
  });

  it("clears the token and fires the 401 handler on 401", async () => {
    setToken("tok");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal("fetch", mockFetch(401, { error: { code: "UNAUTHORIZED", message_en: "x", message_ko: "y" } }));
    await expect(api.accuracy("005930:KRX")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });

  it("attaches the Authorization header when a token is set", async () => {
    setToken("tok123");
    const f = mockFetch(200, { data: {}, meta: {} });
    vi.stubGlobal("fetch", f);
    await api.indexes();
    const init = f.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
  });

  it("localizes error messages", () => {
    const e = new ApiError(404, "SYMBOL_NOT_FOUND", "Unknown stock.", "알 수 없는 종목이에요.");
    expect(e.localized("ko")).toBe("알 수 없는 종목이에요.");
    expect(e.localized("en")).toBe("Unknown stock.");
  });
});
