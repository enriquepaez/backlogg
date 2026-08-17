import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `AdminPage` is an async Server Component (`getTranslations` from
// `next-intl/server`) — same mocking approach `admin/layout.test.tsx` uses.
// The auth+`is_admin` gate this file used to test (`admin_role_gate` fix)
// moved to `@/app/[locale]/admin/layout.tsx` with FE-33 — see that file's
// own test for gate coverage. This page has nothing left to check beyond
// "it renders its two panels".
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
  setRequestLocale: vi.fn(),
}));

// `AdminStatsPanel`/`AdminReportsPanel` are Client Components with their own
// `fetch` calls against `/api/admin/*` — out of scope here (each covered by
// its own test), same rationale the old `admin/page.test.tsx` used.
vi.mock("@/components/admin-stats-panel", () => ({
  AdminStatsPanel: () => <div data-testid="admin-stats-panel" />,
}));
vi.mock("@/components/admin-reports-panel", () => ({
  AdminReportsPanel: () => <div data-testid="admin-reports-panel" />,
}));

const { default: AdminPage } = await import("./page");

const buildProps = (locale: string) => ({
  params: Promise.resolve({ locale }),
  searchParams: Promise.resolve({}),
});

describe("AdminPage", () => {
  it("renders the stats and reports panels", async () => {
    render(await AdminPage(buildProps("en")));

    expect(screen.getByTestId("admin-stats-panel")).toBeInTheDocument();
    expect(screen.getByTestId("admin-reports-panel")).toBeInTheDocument();
  });

  it("renders the heading and description", async () => {
    render(await AdminPage(buildProps("en")));

    expect(screen.getByRole("heading", { name: "heading" })).toBeInTheDocument();
    expect(screen.getByText("description")).toBeInTheDocument();
  });
});
