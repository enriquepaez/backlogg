import { StrictMode, act } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `search-pagination.test.tsx` for mocking `@/i18n/navigation`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { VerifyEmailStatus } = await import("./verify-email-status");

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  server.resetHandlers();
});

describe("VerifyEmailStatus", () => {
  it("shows a missing-token error and never calls the backend when there is no token", async () => {
    const confirmCall = vi.fn();
    server.use(
      http.post("/api/auth/verify/confirm", () => {
        confirmCall();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<VerifyEmailStatus token={undefined} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("missingToken");
    expect(confirmCall).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "backHome" })).toHaveAttribute("href", "/");
  });

  it("shows a loading state, then a success message and continue link on 200", async () => {
    server.use(http.post("/api/auth/verify/confirm", () => HttpResponse.json({ ok: true })));

    render(<VerifyEmailStatus token="a-valid-token" />);

    expect(await screen.findByRole("status")).toHaveTextContent(/verifying|success/);

    await waitFor(() =>
      expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("success"),
    );
    expect(screen.getByRole("link", { name: "continueCta" })).toHaveAttribute("href", "/login");
  });

  it("shows an invalid-token message on a 400 response", async () => {
    server.use(
      http.post("/api/auth/verify/confirm", () =>
        HttpResponse.json({ error: "invalid_token" }, { status: 400 }),
      ),
    );

    render(<VerifyEmailStatus token="an-expired-token" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("invalidToken");
    expect(screen.getByRole("link", { name: "backHome" })).toBeInTheDocument();
  });

  it("shows a generic error message on an unexpected backend status", async () => {
    server.use(
      http.post("/api/auth/verify/confirm", () => new HttpResponse(null, { status: 500 })),
    );

    render(<VerifyEmailStatus token="some-token" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("error");
  });

  it("calls the confirm endpoint once and resolves to success under React StrictMode's double-invoked effects", async () => {
    // Regression test: `next dev` renders with StrictMode on, which mounts,
    // cleans up, and remounts each component once in dev. Plain `render()`
    // (used by every other test in this file) never exercises that cycle, so
    // it couldn't catch a real bug where the guard against a duplicate fetch
    // also caused the *only* fetch's result to be discarded, leaving the UI
    // stuck on "loading" forever in the real browser.
    const confirmCall = vi.fn();
    server.use(
      http.post("/api/auth/verify/confirm", () => {
        confirmCall();
        return HttpResponse.json({ ok: true });
      }),
    );

    await act(async () => {
      render(
        <StrictMode>
          <VerifyEmailStatus token="a-valid-token" />
        </StrictMode>,
      );
    });

    await waitFor(() => expect(confirmCall).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("success"),
    );
  });
});
