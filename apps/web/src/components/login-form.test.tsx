import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `register-form.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
const push = vi.fn();
const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push, refresh }),
  Link: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { LoginForm } = await import("./login-form");

function fillValidForm() {
  fireEvent.change(screen.getByLabelText("usernameLabel"), { target: { value: "someuser" } });
  fireEvent.change(screen.getByLabelText("passwordLabel"), { target: { value: "somepassword" } });
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  // `shouldAdvanceTime` lets the fake clock track real elapsed time so the
  // MSW-mocked `fetch` calls (which schedule their own internal timers) can
  // still resolve, while `useCountdown`'s one-second ticks are exercised in
  // isolation (with plain fake timers) in `src/lib/use-countdown.test.ts` —
  // here the 429 case only asserts the immediate "waiting, disabled" state
  // and then waits out the real ~1s countdown via `waitFor`.
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LoginForm", () => {
  it("links to /forgot-password (FE-16)", () => {
    render(<LoginForm />);

    expect(screen.getByRole("link", { name: "forgotPasswordLink" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("renders no error line for any field before any error occurs", () => {
    render(<LoginForm />);

    const usernameInput = screen.getByLabelText("usernameLabel");
    const placeholder = usernameInput.closest("div")?.querySelector("p");

    expect(placeholder).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the first required-field error above the button and never hits the network for an empty submission", async () => {
    const loginCall = vi.fn();
    server.use(
      http.post("/api/auth/login", () => {
        loginCall();
        return HttpResponse.json({ ok: true });
      }),
    );

    render(<LoginForm />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    // Only one message shows at a time, in field order — the reserved slot
    // above the button is the single place any error surfaces, per the
    // user's explicit request that nothing render under the inputs.
    expect(await screen.findByText("username")).toBeInTheDocument();
    expect(screen.queryByText("password")).not.toBeInTheDocument();
    expect(loginCall).not.toHaveBeenCalled();
  });

  it("shows no error while typing or on blur — only on submit", async () => {
    render(<LoginForm />);

    const usernameInput = screen.getByLabelText("usernameLabel");
    await act(async () => {
      fireEvent.focus(usernameInput);
      fireEvent.blur(usernameInput);
    });

    expect(screen.queryByText("username")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("on success, redirects home and refreshes the session-aware nav", async () => {
    server.use(http.post("/api/auth/login", () => HttpResponse.json({ ok: true })));

    render(<LoginForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(refresh).toHaveBeenCalled();
  });

  it("shows an invalid-credentials message on 401 without redirecting", async () => {
    server.use(
      http.post("/api/auth/login", () => HttpResponse.json({ error: "invalid_credentials" }, { status: 401 })),
    );

    render(<LoginForm />);
    fillValidForm();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("invalidCredentials")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("surfaces a 429 as a disabled submit with a countdown, re-enabling at zero", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({ error: "rate_limited" }, { status: 429, headers: { "Retry-After": "1" } }),
      ),
    );

    render(<LoginForm />);
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
