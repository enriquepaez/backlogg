import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `SiteHeader` is an async Server Component (`getTranslations` from
// `next-intl/server`, `getCurrentUser` from `@/lib/api-fetch`, both
// server-only). None of that runs in this jsdom+Vitest environment, so every
// dependency is mocked — the same approach `login-form.test.tsx` /
// `register-form.test.tsx` use for the client-side `next-intl` +
// `@/i18n/navigation` hooks, extended here to the server-side equivalents.
// The resulting element tree (once awaited) is a plain React tree, so it
// renders with Testing Library exactly like any client component.
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

// FE-55 "navbar decluttering" moved these from their own always-visible
// controls into `UserNav`'s menu (session) / `GuestSettingsMenu`'s (no
// session) as `DropdownMenuSub` entries — their own behavior is covered by
// `language-switcher.test.tsx`/`mode-toggle.test.tsx`, out of scope here.
vi.mock("@/components/language-switcher", () => ({
  LanguageMenuItem: () => <div data-testid="language-menu-item" />,
}));

vi.mock("@/components/mode-toggle", () => ({
  ThemeMenuItem: () => <div data-testid="theme-menu-item" />,
}));

// `NotificationBell` (FE-24) is a Client Component with its own `fetch`
// calls (unread count on mount) — out of scope for this Server Component's
// own tests (covered by `notification-bell.test.tsx`), same rationale as
// mocking `LanguageSwitcher`/`ModeToggle` above.
vi.mock("@/components/notification-bell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

const { SiteHeader } = await import("./site-header");

// Radix's `DropdownMenuTrigger` opens on `pointerdown` (mouse button 0), not
// `click` — see `user-nav.test.tsx`'s `openMenu()` for the same note. Used
// here to open the "Explore"/"Activity" `NavMenu` dropdowns and
// `GuestSettingsMenu`.
function openDropdown(name: string) {
  fireEvent.pointerDown(screen.getByRole("button", { name }), {
    button: 0,
    ctrlKey: false,
  });
}

describe("SiteHeader", () => {
  it("shows a login link and no account menu when anonymous", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    render(await SiteHeader());

    expect(screen.getByRole("link", { name: "login" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "accountMenu" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("notification-bell")).not.toBeInTheDocument();
    // "Activity" (Feed/For you) is session-gated (FE-23/FE-27) — its `NavMenu`
    // trigger shouldn't render at all when anonymous.
    expect(screen.queryByRole("button", { name: "activity" })).not.toBeInTheDocument();
    // Same for the standalone `Library` link (FE-20/21/36).
    expect(screen.queryByRole("link", { name: "library" })).not.toBeInTheDocument();
  });

  it("removes the old Home/Showcase links from the nav (FE-55)", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    render(await SiteHeader());

    // The brand link (pointing at "/") is the only link named "home"-ish;
    // the dedicated "Home" nav link is gone. "showcase" is gone too — the
    // route still exists, only the public link was removed.
    expect(screen.queryByRole("link", { name: "home" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "showcase" })).not.toBeInTheDocument();
    // `Search` stays a standalone link, not folded into any dropdown.
    expect(screen.getByRole("link", { name: "search" })).toHaveAttribute("href", "/search");
  });

  it("groups Trending/Genres behind the Explore dropdown", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    render(await SiteHeader());

    // Collapsed by default: not rendered as top-level links anymore.
    expect(screen.queryByRole("link", { name: "trending" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "genres" })).not.toBeInTheDocument();

    openDropdown("explore");

    expect(await screen.findByRole("menuitem", { name: "trending" })).toHaveAttribute(
      "href",
      "/trending",
    );
    expect(screen.getByRole("menuitem", { name: "genres" })).toHaveAttribute("href", "/genres");
  });

  it("shows a settings menu (language/theme) for the anonymous visitor", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    render(await SiteHeader());

    openDropdown("settings");

    expect(await screen.findByTestId("language-menu-item")).toBeInTheDocument();
    expect(screen.getByTestId("theme-menu-item")).toBeInTheDocument();
  });

  it("shows the account menu (name/avatar) and no login link when authenticated", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "alice",
      display_name: "Alice A.",
      avatar_url: null,
      email: "alice@example.com",
      email_verified: true,
      bio: null,
    });

    render(await SiteHeader());

    expect(screen.getByRole("button", { name: "accountMenu" })).toBeInTheDocument();
    expect(screen.getByText("Alice A.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "login" })).not.toBeInTheDocument();
    expect(screen.getByTestId("notification-bell")).toBeInTheDocument();
    // `Library` stays a standalone link once signed in (FE-55: not folded
    // into the "Activity" dropdown).
    expect(screen.getByRole("link", { name: "library" })).toHaveAttribute(
      "href",
      "/u/alice/library",
    );
  });

  it("groups Feed/For you behind the Activity dropdown once signed in", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "alice",
      display_name: "Alice A.",
      avatar_url: null,
      email: "alice@example.com",
      email_verified: true,
      bio: null,
    });

    render(await SiteHeader());

    expect(screen.queryByRole("link", { name: "recommendations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "feed" })).not.toBeInTheDocument();

    openDropdown("activity");

    expect(await screen.findByRole("menuitem", { name: "feed" })).toHaveAttribute(
      "href",
      "/feed",
    );
    expect(screen.getByRole("menuitem", { name: "recommendations" })).toHaveAttribute(
      "href",
      "/recommendations",
    );
  });
});
