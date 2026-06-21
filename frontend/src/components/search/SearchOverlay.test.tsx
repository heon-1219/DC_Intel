import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import SearchOverlay from "./SearchOverlay";
import { LangProvider } from "../../hooks/useT";

const RESULTS = {
  data: {
    query: "apple",
    results: [
      {
        company_name_en: "Apple Inc.",
        company_name_ko: "애플",
        listings: [
          {
            instrument: "AAPL:NASDAQ",
            symbol: "AAPL",
            exchange: "NASDAQ",
            board: null,
            currency: "USD",
            is_primary: true,
            kind: "common",
            last_price: 195,
            price_as_of: "2026-06-15T01:00:00Z",
            fx_rate: 1.0,
            diff_vs_primary_pct: null,
          },
        ],
      },
    ],
  },
  meta: { source: "internal", data_as_of: "x", is_stale: false, cache: "miss", request_id: "r" },
};

function renderOverlay() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <MemoryRouter>
          <SearchOverlay open onClose={() => {}} />
        </MemoryRouter>
      </LangProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("SearchOverlay", () => {
  it("prompts for more characters before searching", () => {
    renderOverlay();
    expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument();
  });

  it("debounces, fetches, and renders grouped results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => RESULTS }),
    );
    const user = userEvent.setup();
    renderOverlay();
    await user.type(screen.getByRole("combobox"), "apple");
    expect(await screen.findByText("Apple Inc.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("$195.00")).toBeInTheDocument());
  });
});
