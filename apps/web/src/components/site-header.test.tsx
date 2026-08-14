import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/components/language-switcher", () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}));

vi.mock("@/components/mode-toggle", () => ({
  ModeToggle: () => <div data-testid="mode-toggle" />,
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

describe("SiteHeader", () => {
  it("shows a login link and no account menu when anonymous", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    render(await SiteHeader());

    expect(screen.getByRole("link", { name: "login" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "accountMenu" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("notification-bell")).not.toBeInTheDocument();
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
  });
});
