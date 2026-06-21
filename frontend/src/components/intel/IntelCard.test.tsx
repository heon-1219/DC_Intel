import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import IntelCard from "./IntelCard";
import type { IntelCluster } from "../../api/types";
import { LangProvider } from "../../hooks/useT";

const cluster: IntelCluster = {
  cluster_id: "c1",
  status: "UNCONFIRMED",
  badge: { label: "Unconfirmed — rumor", style: "speculation", disclaimer: "unverified" },
  sentiment: "bullish",
  sentiment_confidence: 0.78,
  item_count: 3,
  distinct_authors: 2,
  max_credibility: 65,
  credibility_band: "Moderate",
  coordinated_warning: false,
  lead_time_minutes: null,
  timeline: [],
  items: [
    {
      id: 1,
      source: "reddit",
      author_handle: "u1",
      url: null,
      content_snippet: "huge news incoming",
      lang: "en",
      posted_at: new Date().toISOString(),
      credibility_score: 65,
      sentiment: "bullish",
      sentiment_confidence: 0.78,
      confirmed: false,
    },
  ],
  confirm_url: null,
  stock: null,
};

const wrap = (c: IntelCluster) =>
  render(
    <LangProvider>
      <MemoryRouter>
        <IntelCard cluster={c} />
      </MemoryRouter>
    </LangProvider>,
  );

describe("IntelCard", () => {
  it("renders the badge label + snippet", () => {
    wrap(cluster);
    expect(screen.getByText(/Unconfirmed/i)).toBeInTheDocument();
    expect(screen.getByText("huge news incoming")).toBeInTheDocument();
  });

  it("renders nothing when there is no badge (hard pipeline rule)", () => {
    const { container } = wrap({ ...cluster, badge: undefined as unknown as IntelCluster["badge"] });
    expect(container.firstChild).toBeNull();
  });
});
