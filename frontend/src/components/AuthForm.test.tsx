import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuthForm from "./AuthForm";
import { setToken } from "../api/client";
import { AuthProvider } from "../hooks/useAuth";
import { LangProvider } from "../hooks/useT";

function renderLogin() {
  return render(
    <LangProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<AuthForm mode="login" />} />
            <Route path="/dashboard" element={<div>DASHBOARD</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </LangProvider>,
  );
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status, ok: status < 400, json: async () => body }),
  );
}

afterEach(() => {
  setToken(null);
  vi.restoreAllMocks();
});

describe("AuthForm (login)", () => {
  it("shows a validation error for a bad email on submit", async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/Email/i), "not-an-email");
    await user.type(screen.getByLabelText(/Password/i), "longenough1");
    await user.click(screen.getByRole("button", { name: /Log in/i }));
    expect(screen.getByText(/valid email/i)).toBeInTheDocument();
  });

  it("logs in on valid credentials and navigates to the dashboard", async () => {
    mockFetch(200, {
      data: { access_token: "jwt", token_type: "bearer", expires_in: 86400, user: { id: 1, email: "a@b.com", language: "en" } },
      meta: {},
    });
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/Email/i), "a@b.com");
    await user.type(screen.getByLabelText(/Password/i), "Tr0ubadour9x");
    await user.click(screen.getByRole("button", { name: /Log in/i }));
    expect(await screen.findByText("DASHBOARD")).toBeInTheDocument();
  });

  it("renders the invalid-credentials message on 401", async () => {
    mockFetch(401, { error: { code: "INVALID_CREDENTIALS", message_en: "x", message_ko: "y" } });
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/Email/i), "a@b.com");
    await user.type(screen.getByLabelText(/Password/i), "Tr0ubadour9x");
    await user.click(screen.getByRole("button", { name: /Log in/i }));
    expect(await screen.findByText(/doesn't match/i)).toBeInTheDocument();
  });

  it("toggles password visibility", async () => {
    const user = userEvent.setup();
    renderLogin();
    const pw = screen.getByLabelText(/Password/i) as HTMLInputElement;
    expect(pw.type).toBe("password");
    await user.click(screen.getByRole("button", { name: /Show password/i }));
    expect(pw.type).toBe("text");
  });
});
