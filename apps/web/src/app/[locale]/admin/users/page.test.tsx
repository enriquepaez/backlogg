import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `AdminUsersDirectoryPanel` is a Client Component with its own fetch/state —
// out of scope here (covered by its own test), same rationale
// `admin/page.test.tsx` uses for mocking `AdminStatsPanel`/`AdminReportsPanel`.
vi.mock("@/components/admin-users-directory-panel", () => ({
  AdminUsersDirectoryPanel: () => <div data-testid="admin-users-directory-panel" />,
}));

const { default: AdminUsersPage } = await import("./page");

describe("AdminUsersPage", () => {
  it("renders the users directory panel", () => {
    render(<AdminUsersPage />);

    expect(screen.getByTestId("admin-users-directory-panel")).toBeInTheDocument();
  });
});
