import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./ErrorBoundary";
import { LangProvider } from "../../hooks/useT";

function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("renders a localized fallback instead of crashing when a child throws", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <LangProvider>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </LangProvider>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong|문제가 발생했어요/)).toBeInTheDocument();
    spy.mockRestore();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <LangProvider>
        <ErrorBoundary>
          <div>ok content</div>
        </ErrorBoundary>
      </LangProvider>,
    );
    expect(screen.getByText("ok content")).toBeInTheDocument();
  });
});
