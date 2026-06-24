import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import WhisperCard from "./WhisperCard";
import type { WhisperData } from "../../api/types";
import { LangProvider } from "../../hooks/useT";

const META = { source: "internal", data_as_of: "x", is_stale: false, cache: "miss", request_id: "r" };

const base: WhisperData = {
  instrument: "AAPL:NASDAQ",
  status: "corroborated",
  whisper_value: 2.41,
  confidence: 82,
  anchor: 2.3,
  surprise_vs_anchor: 0.11,
  earnings_date: "2026-07-31",
  n_inliers: 5,
  n_outliers_rejected: 1,
  n_distinct_families: 3,
  contributing_families: ["earningswhispers", "estimize", "websearch"],
  inlier_dispersion: 0.03,
  factors: {},
  abstain_reason: null,
  rounds_used: 2,
  computed_at: "2026-07-20T00:00:00Z",
};

function stubFetch(data: WhisperData) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({ data, meta: META }) }),
  );
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <MemoryRouter>
          <WhisperCard listing="AAPL:NASDAQ" />
        </MemoryRouter>
      </LangProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("WhisperCard", () => {
  it("shows a loading skeleton with no layout shift before data arrives", () => {
    stubFetch(base);
    const { container } = renderCard();
    // aria-busy section is the skeleton placeholder, title not yet rendered.
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
  });

  it("renders a corroborated whisper vs consensus with a blue badge", async () => {
    stubFetch(base);
    renderCard();
    expect(await screen.findByText("Corroborated")).toBeInTheDocument();
    expect(screen.getByText("2.41")).toBeInTheDocument(); // whisper
    expect(screen.getByText("2.30")).toBeInTheDocument(); // consensus
    expect(screen.getByText("+0.11")).toBeInTheDocument(); // positive surprise
    expect(screen.getByText(/82% confidence/i)).toBeInTheDocument();
    expect(screen.getByText(/5 agreeing estimates/i)).toBeInTheDocument();
    expect(screen.getByText("earningswhispers")).toBeInTheDocument();
  });

  it("renders a tentative whisper with an amber badge and a negative surprise", async () => {
    stubFetch({ ...base, status: "tentative", whisper_value: 2.2, surprise_vs_anchor: -0.1 });
    renderCard();
    expect(await screen.findByText("Tentative")).toBeInTheDocument();
    expect(screen.getByText("-0.10")).toBeInTheDocument();
  });

  it("shows an honest abstain state for no_reliable_whisper (never a fake number)", async () => {
    stubFetch({
      ...base,
      status: "no_reliable_whisper",
      whisper_value: null,
      confidence: 38,
      surprise_vs_anchor: null,
      abstain_reason: "sources disagree",
    });
    renderCard();
    expect(await screen.findByText("No reliable whisper")).toBeInTheDocument();
    expect(screen.getByText(/sources disagree/i)).toBeInTheDocument();
    expect(screen.queryByText("2.41")).not.toBeInTheDocument();
  });

  it("shows a quiet empty state when nothing is computed yet (status null)", async () => {
    stubFetch({
      ...base,
      status: null,
      whisper_value: null,
      confidence: null,
      anchor: null,
      surprise_vs_anchor: null,
      earnings_date: null,
      n_inliers: 0,
      n_distinct_families: 0,
      contributing_families: [],
    });
    renderCard();
    expect(await screen.findByText(/No upcoming earnings whisper/i)).toBeInTheDocument();
  });

  it("shows the retry error card when the request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 500,
        ok: false,
        json: async () => ({ error: { code: "ERROR", message_en: "x", message_ko: "x", request_id: "r" } }),
      }),
    );
    renderCard();
    await waitFor(() => expect(screen.getByText(/Tap to retry/i)).toBeInTheDocument());
  });
});
