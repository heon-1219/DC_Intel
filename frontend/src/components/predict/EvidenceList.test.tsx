import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import EvidenceList from "./EvidenceList";
import type { EvidenceItem } from "../../api/types";
import { LangProvider } from "../../hooks/useT";

const items: EvidenceItem[] = [
  { kind: "technical", text_en: "RSI rising", text_ko: "RSI 상승", contribution_pct: 40 },
  { kind: "sentiment", text_en: "Positive buzz", text_ko: "긍정 여론", contribution_pct: 35 },
  { kind: "technical", text_en: "MA cross up", text_ko: "이평선 상향", contribution_pct: 25 },
];

describe("EvidenceList", () => {
  it("renders each bullet with its localized text and contribution", () => {
    render(
      <LangProvider>
        <EvidenceList items={items} lang="en" />
      </LangProvider>,
    );
    expect(screen.getByText("RSI rising")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
  });

  it("shows the empty state when there are no signals", () => {
    render(
      <LangProvider>
        <EvidenceList items={[]} lang="en" />
      </LangProvider>,
    );
    expect(screen.getByText(/Not enough signals/i)).toBeInTheDocument();
  });
});
