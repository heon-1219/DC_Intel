import { describe, expect, it } from "vitest";

import { minCharsOk } from "./search";

describe("minCharsOk", () => {
  it("requires 2 latin chars", () => {
    expect(minCharsOk("a")).toBe(false);
    expect(minCharsOk("ap")).toBe(true);
  });
  it("allows a single Hangul char", () => {
    expect(minCharsOk("삼")).toBe(true);
  });
  it("ignores surrounding whitespace", () => {
    expect(minCharsOk("  ")).toBe(false);
    expect(minCharsOk(" ap ")).toBe(true);
  });
});
