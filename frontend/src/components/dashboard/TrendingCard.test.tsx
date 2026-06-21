import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import TrendingCard from "./TrendingCard";
import type { TrendingCard as Card } from "../../api/types";
import { LangProvider } from "../../hooks/useT";

const base: Card = {
  instrument: "AAPL:NASDAQ",
  name_en: "Apple",
  name_ko: "애플",
  price: 195,
  currency: "USD",
  change_pct: 3.2,
  volume: 1,
  sparkline: [1, 2, 3],
  win_rate_pct: 71,
  n_closed: 143,
};

const wrap = (card: Card) =>
  render(
    <LangProvider>
      <MemoryRouter>
        <TrendingCard card={card} lang="en" />
      </MemoryRouter>
    </LangProvider>,
  );

describe("TrendingCard", () => {
  it("shows the win-rate badge with the rounded pct when scored", () => {
    wrap(base);
    expect(screen.getByText(/🎯 71%/)).toBeInTheDocument();
    expect(screen.getByText("+3.20%")).toBeInTheDocument();
  });

  it("shows 'collecting' when win_rate_pct is null (low sample)", () => {
    wrap({ ...base, win_rate_pct: null });
    expect(screen.getByText(/collecting/i)).toBeInTheDocument();
  });
});
