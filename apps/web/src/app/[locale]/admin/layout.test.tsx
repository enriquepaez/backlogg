import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `AdminLayout` is an async Server Component (`setRequestLocale` from
// `next-intl/server`, `getCurrentUser` from `@/lib/api-fetch`, `redirect`
// from `@/i18n/navigation`, all server-only) — same mocking approach the
// old `admin/page.test.tsx` used before this feature (FE-33) moved the
// auth+`is_admin` gate here.
//
// This test exists specifically for the `admin_role_gate` fix (originally
// covered by `admin/page.test.tsx`): unlike every other protected page in
// this repo (`/settings`, `/recommendations`, ...), `/admin/*` has a SECOND
// authorization check beyond "is there a session" — `user.is_admin` — and a
// regression here silently reopens the vulnerability that fix closed, now
// for every route under `/admin/*` at once instead of just `/admin` itself.
vi.mock("next-intl/server", () => ({
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

// `AdminSidebar` is a Client Component with its own `usePathname`/i18n
// concerns — out of scope here (covered by its own test), same rationale
// `admin/page.test.tsx` used for mocking `AdminStatsPanel` et al.
vi.mock("@/components/admin-sidebar", () => ({
  AdminSidebar: () => <div data-testid="admin-sidebar" />,
}));

const { default: AdminLayout } = await import("./layout");

const buildProps = (locale: string) => ({
  children: <div data-testid="admin-child">child content</div>,
  params: Promise.resolve({ locale }),
});

describe("AdminLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to /login when there is no session", async () => {
    getCurrentUser.mockResolvedValueOnce(null);

    await AdminLayout(buildProps("en"));

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

    await AdminLayout(buildProps("en"));

    expect(redirect).toHaveBeenCalledWith({ href: "/", locale: "en" });
    expect(redirect).not.toHaveBeenCalledWith(expect.objectContaining({ href: "/login" }));
  });

  it("renders the sidebar and children for a signed-in admin user, without redirecting", async () => {
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

    render(await AdminLayout(buildProps("en")));

    expect(screen.getByTestId("admin-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("admin-child")).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });
});
