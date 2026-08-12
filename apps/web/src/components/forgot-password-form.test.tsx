import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `login-form.test.tsx` for mocking `next-intl`.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { ForgotPasswordForm } = await import("./forgot-password-form");

afterEach(() => {
  server.resetHandlers();
});

function fillValidEmail() {
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "someone@example.com" },
  });
}

describe("ForgotPasswordForm", () => {
  it("renders no error line before any error occurs", () => {
    render(<ForgotPasswordForm />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a field error and never hits the network for an invalid email", async () => {
    const forgotCall = vi.fn();
    server.use(
      http.post("/api/auth/password/forgot", () => {
        forgotCall();
        return HttpResponse.json({ ok: true }, { status: 202 });
      }),
    );

    render(<ForgotPasswordForm />);
    fireEvent.change(screen.getByLabelText("emailLabel"), { target: { value: "not-an-email" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("email")).toBeInTheDocument();
    expect(forgotCall).not.toHaveBeenCalled();
  });

  it("shows the same neutral success message whether or not the backend's 202 corresponds to a real account", async () => {
    server.use(
      http.post("/api/auth/password/forgot", () => HttpResponse.json({ ok: true }, { status: 202 })),
    );

    render(<ForgotPasswordForm />);
    fillValidEmail();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByRole("status")).toHaveTextContent("success");
  });

  it("also shows the neutral success message on a backend 422 (still no enumeration)", async () => {
    server.use(
      http.post("/api/auth/password/forgot", () =>
        HttpResponse.json({ error: "validation_error" }, { status: 422 }),
      ),
    );

    render(<ForgotPasswordForm />);
    fillValidEmail();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByRole("status")).toHaveTextContent("success");
  });

  it("shows a generic error on an unexpected backend status", async () => {
    server.use(
      http.post("/api/auth/password/forgot", () => new HttpResponse(null, { status: 500 })),
    );

    render(<ForgotPasswordForm />);
    fillValidEmail();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("genericError")).toBeInTheDocument();
  });
});
