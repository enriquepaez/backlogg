import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `login-form.test.tsx`/`register-form.test.tsx` for
// mocking `@/i18n/navigation` and `next-intl`.
const push = vi.fn();
const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

const { AccountProfileForm } = await import("./account-profile-form");

const initial = {
  displayName: "Alice A.",
  bio: "Hello there",
  avatarUrl: "https://example.com/a.png",
};

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  toastSuccess.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AccountProfileForm", () => {
  it("pre-fills the fields from the initial profile values", () => {
    render(<AccountProfileForm initial={initial} />);

    expect(screen.getByLabelText("displayNameLabel")).toHaveValue("Alice A.");
    expect(screen.getByLabelText("bioLabel")).toHaveValue("Hello there");
    expect(screen.getByLabelText("avatarUrlLabel")).toHaveValue("https://example.com/a.png");
  });

  it("falls back to empty fields when the profile has no values set", () => {
    render(<AccountProfileForm initial={{ displayName: null, bio: null, avatarUrl: null }} />);

    expect(screen.getByLabelText("displayNameLabel")).toHaveValue("");
    expect(screen.getByLabelText("bioLabel")).toHaveValue("");
    expect(screen.getByLabelText("avatarUrlLabel")).toHaveValue("");
  });

  it("shows a field error and never hits the network for a malformed avatar URL", async () => {
    const patchCall = vi.fn();
    server.use(
      http.patch("/api/users/me", () => {
        patchCall();
        return HttpResponse.json({}, { status: 200 });
      }),
    );

    render(<AccountProfileForm initial={initial} />);
    fireEvent.change(screen.getByLabelText("avatarUrlLabel"), {
      target: { value: "not-a-url" },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("avatarUrl")).toBeInTheDocument();
    expect(patchCall).not.toHaveBeenCalled();
  });

  it("submits display_name/bio/avatar_url, translating a blanked field to null", async () => {
    let forwardedBody: unknown;
    server.use(
      http.patch("/api/users/me", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(
          { username: "alice", email: "a@example.com", display_name: "Alice A.", bio: null, avatar_url: "https://example.com/a.png", email_verified: true },
          { status: 200 },
        );
      }),
    );

    render(<AccountProfileForm initial={initial} />);
    fireEvent.change(screen.getByLabelText("bioLabel"), { target: { value: "" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() =>
      expect(forwardedBody).toEqual({
        display_name: "Alice A.",
        bio: null,
        avatar_url: "https://example.com/a.png",
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(refresh).toHaveBeenCalled();
  });

  it("shows an unauthorized message on a 401 without a toast", async () => {
    server.use(http.patch("/api/users/me", () => new HttpResponse(null, { status: 401 })));

    render(<AccountProfileForm initial={initial} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows a generic error on an unexpected backend failure", async () => {
    server.use(http.patch("/api/users/me", () => new HttpResponse(null, { status: 500 })));

    render(<AccountProfileForm initial={initial} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("genericError")).toBeInTheDocument();
  });
});
