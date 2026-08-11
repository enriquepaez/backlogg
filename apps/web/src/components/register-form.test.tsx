import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `browse-filters.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`: `useTranslations` is mocked to an identity function so
// assertions can match on message keys (e.g. field names for the zod-driven
// error messages, per `applyZodFieldErrors`'s doc comment) without a real
// `NextIntlClientProvider`.
const push = vi.fn();
const refresh = vi.fn();
const toastSuccess = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

// Same rationale as `logout-button.tsx`'s toast usage: mocked to a spy so
// the "account created, chained login failed" fallback can assert the
// toast fired without a real `Toaster` (mounted in `[locale]/layout.tsx`,
// out of scope for this component test).
vi.mock("sonner", () => ({
  toast: { success: toastSuccess },
}));

const { RegisterForm } = await import("./register-form");

function fillValidForm() {
  fireEvent.change(screen.getByLabelText("usernameLabel"), {
    target: { value: "valid_user-1" },
  });
  fireEvent.change(screen.getByLabelText("emailLabel"), {
    target: { value: "user@example.com" },
  });
  fireEvent.change(screen.getByLabelText("passwordLabel"), {
    target: { value: "longenough1" },
  });
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  toastSuccess.mockClear();
  // See `login-form.test.tsx`'s matching comment: `shouldAdvanceTime` lets
  // the fake clock track real elapsed time so the MSW-mocked `fetch` calls
  // still resolve; `useCountdown`'s tick-by-tick behavior is covered in
  // isolation by `src/lib/use-countdown.test.ts`.
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RegisterForm", () => {
  it("renders no error line for any field before any error occurs", () => {
    render(<RegisterForm />);

    const usernameInput = screen.getByLabelText("usernameLabel");
    const placeholder = usernameInput.closest("div")?.querySelector("p");

    expect(placeholder).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the first zod field error above the button and never hits the network for an invalid submission", async () => {
    const registerCall = vi.fn();
    server.use(
      http.post("/api/auth/register", () => {
        registerCall();
        return HttpResponse.json({ ok: true }, { status: 201 });
      }),
    );

    render(<RegisterForm />);

    fireEvent.change(screen.getByLabelText("usernameLabel"), { target: { value: "ab" } });
    fireEvent.change(screen.getByLabelText("emailLabel"), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText("passwordLabel"), { target: { value: "short" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    // Only one message shows at a time, in field order — the reserved slot
    // above the button is the single place any error surfaces, per the
    // user's explicit request that nothing render under the inputs.
    expect(await screen.findByText("username")).toBeInTheDocument();
    expect(screen.queryByText("email")).not.toBeInTheDocument();
    expect(screen.queryByText("password")).not.toBeInTheDocument();
    expect(registerCall).not.toHaveBeenCalled();
  });

  it("shows no error while typing or on blur — only on submit", async () => {
    render(<RegisterForm />);

    const usernameInput = screen.getByLabelText("usernameLabel");
    await act(async () => {
      fireEvent.change(usernameInput, { target: { value: "invalid username!" } });
      fireEvent.blur(usernameInput);
    });

    expect(screen.queryByText("username")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("on 201, chains a login with the same credentials and redirects home", async () => {
    let loginBody: unknown;
    server.use(
      http.post("/api/auth/register", () => HttpResponse.json({ ok: true }, { status: 201 })),
      http.post("/api/auth/login", async ({ request }) => {
        loginBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<RegisterForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(refresh).toHaveBeenCalled();
    expect(loginBody).toEqual({ username: "valid_user-1", password: "longenough1" });
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("falls back to /login when registration succeeds but the chained login fails", async () => {
    server.use(
      http.post("/api/auth/register", () => HttpResponse.json({ ok: true }, { status: 201 })),
      http.post("/api/auth/login", () => HttpResponse.json({ error: "rate_limited" }, { status: 429 })),
    );

    render(<RegisterForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(toastSuccess).toHaveBeenCalledWith("accountCreated");
  });

  it("shows a conflict message on 409 without redirecting", async () => {
    server.use(http.post("/api/auth/register", () => HttpResponse.json({ error: "conflict" }, { status: 409 })));

    render(<RegisterForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("conflict")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("surfaces a 429 as a disabled submit with a countdown, re-enabling at zero", async () => {
    server.use(
      http.post("/api/auth/register", () =>
        HttpResponse.json({ error: "rate_limited" }, { status: 429, headers: { "Retry-After": "1" } }),
      ),
    );

    render(<RegisterForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("waiting")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "submit" })).toBeDisabled();

    // `useCountdown`'s own tick-by-tick behavior is covered in isolation by
    // `src/lib/use-countdown.test.ts` — this just waits out the real ~1s
    // countdown (the fake clock is auto-advancing, see `beforeEach` above).
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole("button", { name: "submit" })).not.toBeDisabled();
  });
});
