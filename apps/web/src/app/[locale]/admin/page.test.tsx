import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `AdminPage` is an async Server Component (`getTranslations`/
// `setRequestLocale` from `next-intl/server`, `getCurrentUser` from
// `@/lib/api-fetch`, `redirect` from `@/i18n/navigation`, all server-only),
// same mocking approach `site-header.test.tsx` uses for its Server Component.
//
// This test exists specifically for the `admin_role_gate` fix: unlike every
// other protected page in this repo (`/settings`, `/recommendations`, ...),
// this one has a SECOND authorization check beyond "is there a session" —
// `user.is_admin` — and that check is exactly what was missing before this
// fix (any authenticated user could reach `/admin`). It is worth a real test
// despite there being no other precedent for testing a `[locale]` page.tsx
// Server Component in this repo, because a regression here silently reopens
// the vulnerability this fix closes.
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
  setRequestLocale: vi.fn(),
}));

const redirect = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  redirect: (...args: unknown[]) => redirect(...args),
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

// `AdminStatsPanel`/`AdminReportsPanel`/`AdminModerationPanel` are Client
// Components with their own `fetch` calls against `/api/admin/*` — out of
// scope here (each covered by its own test), same rationale
// `site-header.test.tsx` uses for mocking `NotificationBell`.
// `AdminModerationPanel`'s mock echoes its `isSuperadmin` prop into the DOM
// so this file can assert `AdminPage` forwards `user.is_superadmin`
// correctly (FE-30) — the one prop this page passes down at all.
vi.mock("@/components/admin-stats-panel", () => ({
  AdminStatsPanel: () => <div data-testid="admin-stats-panel" />,
}));
vi.mock("@/components/admin-reports-panel", () => ({
  AdminReportsPanel: () => <div data-testid="admin-reports-panel" />,
}));
vi.mock("@/components/admin-moderation-panel", () => ({
  AdminModerationPanel: ({ isSuperadmin }: { isSuperadmin: boolean }) => (
    <div data-testid="admin-moderation-panel" data-is-superadmin={String(isSuperadmin)} />
  ),
}));

const { default: AdminPage } = await import("./page");

const buildProps = (locale: string) => ({
  params: Promise.resolve({ locale }),
  searchParams: Promise.resolve({}),
});

describe("AdminPage", () => {
  // `redirect`/`getCurrentUser` are shared `vi.fn()` mocks across every test
  // in this file (declared once at module scope so `vi.mock` factories can
  // close over them) — reset between tests so one test's calls/return values
  // never leak into the next, same rationale `mockResolvedValueOnce` already
  // covers for `getCurrentUser` alone but `redirect`'s call history needs
  // clearing too since several assertions check it was NOT called.
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to /login when there is no session", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    await AdminPage(buildProps("en"));

    expect(redirect).toHaveBeenCalledWith({ href: "/login", locale: "en" });
  });

  it("redirects to / (not /login) when the user is signed in but not an admin", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "alice",
      display_name: "Alice A.",
      avatar_url: null,
      email: "alice@example.com",
      email_verified: true,
      bio: null,
      is_admin: false,
    });

    await AdminPage(buildProps("en"));

    expect(redirect).toHaveBeenCalledWith({ href: "/", locale: "en" });
    expect(redirect).not.toHaveBeenCalledWith(expect.objectContaining({ href: "/login" }));
  });

  it("renders the stats panel for a signed-in admin user, without redirecting", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "alice",
      display_name: "Alice A.",
      avatar_url: null,
      email: "alice@example.com",
      email_verified: true,
      bio: null,
      is_admin: true,
      is_superadmin: false,
    });

    render(await AdminPage(buildProps("en")));

    expect(screen.getByTestId("admin-stats-panel")).toBeInTheDocument();
    expect(screen.getByTestId("admin-reports-panel")).toBeInTheDocument();
    expect(screen.getByTestId("admin-moderation-panel")).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("forwards is_superadmin=false to AdminModerationPanel for a regular admin", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "alice",
      display_name: "Alice A.",
      avatar_url: null,
      email: "alice@example.com",
      email_verified: true,
      bio: null,
      is_admin: true,
      is_superadmin: false,
    });

    render(await AdminPage(buildProps("en")));

    expect(screen.getByTestId("admin-moderation-panel")).toHaveAttribute(
      "data-is-superadmin",
      "false",
    );
  });

  it("forwards is_superadmin=true to AdminModerationPanel for a superadmin", async () => {
    getCurrentUser.mockResolvedValueOnce({
      username: "root",
      display_name: "Root",
      avatar_url: null,
      email: "root@example.com",
      email_verified: true,
      bio: null,
      is_admin: true,
      is_superadmin: true,
    });

    render(await AdminPage(buildProps("en")));

    expect(screen.getByTestId("admin-moderation-panel")).toHaveAttribute(
      "data-is-superadmin",
      "true",
    );
  });
});
