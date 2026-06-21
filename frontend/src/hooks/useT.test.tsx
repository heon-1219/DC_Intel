import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LangProvider, interpolate, useT } from "./useT";

function Probe({ k, p }: { k: string; p?: Record<string, string | number> }) {
  const { t } = useT();
  return <span>{t(k, p)}</span>;
}

describe("useT", () => {
  it("looks up a key in the active locale", () => {
    render(
      <LangProvider>
        <Probe k="auth.login.cta" />
      </LangProvider>,
    );
    expect(screen.getByText(/Log in|로그인/)).toBeInTheDocument();
  });

  it("interpolates ICU params", () => {
    render(
      <LangProvider>
        <Probe k="confidence.label" p={{ pct: 72 }} />
      </LangProvider>,
    );
    expect(screen.getByText(/72/)).toBeInTheDocument();
  });

  it("falls back to the raw key when missing", () => {
    render(
      <LangProvider>
        <Probe k="nonexistent.key" />
      </LangProvider>,
    );
    expect(screen.getByText("nonexistent.key")).toBeInTheDocument();
  });
});

describe("interpolate", () => {
  it("replaces known params and leaves unknowns intact", () => {
    expect(interpolate("{a}-{b}", { a: 1 })).toBe("1-{b}");
  });
});
