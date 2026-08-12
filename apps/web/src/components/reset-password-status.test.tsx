import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `verify-email-status.test.tsx` for mocking
// `@/i18n/navigation` and `next-intl`.
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

const { ResetPasswordStatus } = await import("./reset-password-status");

afterEach(() => {
  server.resetHandlers();
});

function fillValidPassword() {
  fireEvent.change(screen.getByLabelText("passwordLabel"), {
    target: { value: "longenough1" },
  });
}

describe("ResetPasswordStatus", () => {
  it("shows a missing-token error and never renders the form when there is no token", async () => {
    const resetCall = vi.fn();
    server.use(
      http.post("/api/auth/password/reset", () => {
        resetCall();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<ResetPasswordStatus token={undefined} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("missingToken");
    expect(screen.queryByLabelText("passwordLabel")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "backToForgot" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
    expect(resetCall).not.toHaveBeenCalled();
  });

  it("shows a field error and never hits the network for a too-short password", async () => {
    const resetCall = vi.fn();
    server.use(
      http.post("/api/auth/password/reset", () => {
        resetCall();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<ResetPasswordStatus token="a-valid-token" />);
    fireEvent.change(screen.getByLabelText("passwordLabel"), { target: { value: "short" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("password")).toBeInTheDocument();
    expect(resetCall).not.toHaveBeenCalled();
  });

  it("on success, forwards the token and password, then shows a continue-to-login link", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post("/api/auth/password/reset", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ detail: "Password changed" });
      }),
    );

    render(<ResetPasswordStatus token="a-valid-token" />);
    fillValidPassword();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByRole("status")).toHaveTextContent("success");
    expect(screen.getByRole("link", { name: "continueCta" })).toHaveAttribute("href", "/login");
    expect(forwardedBody).toEqual({ token: "a-valid-token", new_password: "longenough1" });
  });

  it("shows an invalid-token message on a 400 response", async () => {
    server.use(
      http.post("/api/auth/password/reset", () =>
        HttpResponse.json({ error: "invalid_token" }, { status: 400 }),
      ),
    );

    render(<ResetPasswordStatus token="an-expired-token" />);
    fillValidPassword();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("invalidToken"),
    );
    expect(screen.getByRole("link", { name: "backToForgot" })).toBeInTheDocument();
  });

  it("shows a generic error message on an unexpected backend status, without leaving the form", async () => {
    server.use(
      http.post("/api/auth/password/reset", () => new HttpResponse(null, { status: 500 })),
    );

    render(<ResetPasswordStatus token="some-token" />);
    fillValidPassword();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("error")).toBeInTheDocument();
    expect(screen.getByLabelText("passwordLabel")).toBeInTheDocument();
  });
});
