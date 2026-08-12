import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

// Same rationale as `user-nav.test.tsx`: exercise the real `sonner` module
// shape but spy on the two calls `useResendVerification` can trigger.
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const { AccountVerificationStatus } = await import("./account-verification-status");

beforeEach(() => {
  toastSuccess.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AccountVerificationStatus", () => {
  it("shows the verified message and no verify action when already verified", () => {
    render(<AccountVerificationStatus emailVerified={true} />);

    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the unverified message and a verify action when not verified", () => {
    render(<AccountVerificationStatus emailVerified={false} />);

    expect(screen.getByText("unverified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "verifyAction" })).toBeInTheDocument();
  });

  it("reuses the shared resend-verification action: calls the route and shows a success toast", async () => {
    const resendCall = vi.fn();
    server.use(
      http.post("/api/auth/verify/request", () => {
        resendCall();
        return HttpResponse.json({ ok: true }, { status: 202 });
      }),
    );

    render(<AccountVerificationStatus emailVerified={false} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "verifyAction" }));
    });

    await waitFor(() => expect(resendCall).toHaveBeenCalledTimes(1));
    expect(toastSuccess).toHaveBeenCalledWith("resendVerificationSuccess");
  });

  it("shows an error toast when the resend request fails", async () => {
    server.use(
      http.post("/api/auth/verify/request", () => new HttpResponse(null, { status: 401 })),
    );

    render(<AccountVerificationStatus emailVerified={false} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "verifyAction" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("resendVerificationError"));
  });
});
