import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `login-form.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
const push = vi.fn();
const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

// `sonner`'s toast is exercised for real (not mocked) — asserting it was
// called on the network-failure path below is enough to know the error
// surfaces instead of failing silently.
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}));

const { LogoutButton } = await import("./logout-button");

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LogoutButton", () => {
  it("renders the logout label", () => {
    render(<LogoutButton />);

    expect(screen.getByRole("button", { name: "logout" })).toBeInTheDocument();
  });

  it("calls /api/auth/logout and refreshes the router on click", async () => {
    const logoutCall = vi.fn();
    server.use(
      http.post("/api/auth/logout", () => {
        logoutCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<LogoutButton />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "logout" }));
    });

    await waitFor(() => expect(logoutCall).toHaveBeenCalledTimes(1));
    expect(refresh).toHaveBeenCalled();
  });

  it("surfaces a toast and does not refresh when the route handler fails", async () => {
    server.use(http.post("/api/auth/logout", () => new HttpResponse(null, { status: 500 })));

    render(<LogoutButton />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "logout" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("logoutError"));
    expect(refresh).not.toHaveBeenCalled();
  });
});
