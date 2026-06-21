import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import TimeframeSelector from "./TimeframeSelector";
import { LangProvider } from "../../hooks/useT";

describe("TimeframeSelector", () => {
  it("renders the 6 fixed timeframes as radios and marks the selected one", () => {
    render(
      <LangProvider>
        <TimeframeSelector value="24h" onChange={() => {}} />
      </LangProvider>,
    );
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(6);
    expect(screen.getByRole("radio", { name: "24h" })).toBeChecked();
  });

  it("calls onChange when a timeframe is clicked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LangProvider>
        <TimeframeSelector value="24h" onChange={onChange} />
      </LangProvider>,
    );
    await user.click(screen.getByRole("radio", { name: "5d" }));
    expect(onChange).toHaveBeenCalledWith("5d");
  });
});
