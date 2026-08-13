import type { ReactNode } from "react";
import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `login-form.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`. `Link` is mocked the same way `site-header.test.tsx` does
// it (a plain `<a>`), needed here since FE-17 adds a `Link`-based "settings"
// menu item.
const push = vi.fn();
const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

// Same rationale as `logout-button.test.tsx`: exercise the real `sonner`
// module shape but spy on the two calls this component's actions can trigger
// (`useLogout` never calls `toast.success`; `useResendVerification` calls
// both, depending on outcome).
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const { UserNav } = await import("./user-nav");

const testUser = {
  username: "alice",
  displayName: "Alice A.",
  avatarUrl: null,
  emailVerified: true,
};

// Radix's `DropdownMenuTrigger` opens on `pointerdown` (mouse button 0), not
// `click` — see `@radix-ui/react-dropdown-menu`'s `DropdownMenuTrigger`
// (`onPointerDown` calls `context.onOpenToggle()`). A plain `fireEvent.click`
// never opens it in jsdom.
function openMenu() {
  fireEvent.pointerDown(screen.getByRole("button", { name: "accountMenu" }), {
    button: 0,
    ctrlKey: false,
  });
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  toastSuccess.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UserNav", () => {
  it("shows the display name and initials, with the menu closed by default", () => {
    render(<UserNav user={testUser} />);

    expect(screen.getByText("Alice A.")).toBeInTheDocument();
    expect(screen.getByText("AL")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("falls back to the username when there is no display name", () => {
    render(<UserNav user={{ ...testUser, displayName: null }} />);

    // "alice" appears both as the trigger label and (once opened) the menu
    // label; here the menu is still closed so it renders exactly once.
    expect(screen.getByText("alice")).toBeInTheDocument();
  });

  it("opens the account menu on trigger click and shows a logout entry", async () => {
    render(<UserNav user={testUser} />);

    openMenu();

    expect(await screen.findByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /logout/i })).toBeInTheDocument();
  });

  it("shows a settings entry that links to /settings", async () => {
    render(<UserNav user={testUser} />);

    openMenu();

    const settingsItem = await screen.findByRole("menuitem", { name: /settings/i });
    expect(settingsItem).toHaveAttribute("href", "/settings");
  });

  it("shows a my-profile entry that links to /u/{username}", async () => {
    render(<UserNav user={testUser} />);

    openMenu();

    const profileItem = await screen.findByRole("menuitem", { name: /profile/i });
    expect(profileItem).toHaveAttribute("href", "/u/alice");
  });

  it("closes the menu on Escape", async () => {
    render(<UserNav user={testUser} />);

    openMenu();
    const menu = await screen.findByRole("menu");

    fireEvent.keyDown(menu, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("closes the menu on an outside click", async () => {
    render(
      <div>
        <div data-testid="outside">outside</div>
        <UserNav user={testUser} />
      </div>,
    );

    openMenu();
    await screen.findByRole("menu");

    fireEvent.pointerDown(screen.getByTestId("outside"));
    fireEvent.mouseDown(screen.getByTestId("outside"));

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("selecting logout calls the logout route and refreshes the router", async () => {
    const logoutCall = vi.fn();
    server.use(
      http.post("/api/auth/logout", () => {
        logoutCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<UserNav user={testUser} />);

    openMenu();
    const logoutItem = await screen.findByRole("menuitem", { name: /logout/i });

    await act(async () => {
      fireEvent.click(logoutItem);
    });

    await waitFor(() => expect(logoutCall).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("does not show a resend-verification entry when the email is already verified", async () => {
    render(<UserNav user={testUser} />);

    openMenu();
    await screen.findByRole("menu");

    expect(screen.queryByRole("menuitem", { name: /resendVerification/i })).not.toBeInTheDocument();
  });

  it("shows a resend-verification entry when the email is not verified", async () => {
    render(<UserNav user={{ ...testUser, emailVerified: false }} />);

    openMenu();

    expect(
      await screen.findByRole("menuitem", { name: /resendVerification/i }),
    ).toBeInTheDocument();
  });

  it("selecting resend verification calls the route and shows a success toast", async () => {
    const resendCall = vi.fn();
    server.use(
      http.post("/api/auth/verify/request", () => {
        resendCall();
        return HttpResponse.json({ ok: true }, { status: 202 });
      }),
    );

    render(<UserNav user={{ ...testUser, emailVerified: false }} />);

    openMenu();
    const resendItem = await screen.findByRole("menuitem", { name: /resendVerification/i });

    await act(async () => {
      fireEvent.click(resendItem);
    });

    await waitFor(() => expect(resendCall).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("resendVerificationSuccess"));
  });

  it("shows an error toast when resending verification fails", async () => {
    server.use(
      http.post("/api/auth/verify/request", () => new HttpResponse(null, { status: 401 })),
    );

    render(<UserNav user={{ ...testUser, emailVerified: false }} />);

    openMenu();
    const resendItem = await screen.findByRole("menuitem", { name: /resendVerification/i });

    await act(async () => {
      fireEvent.click(resendItem);
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("resendVerificationError"));
  });
});
