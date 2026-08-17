import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
  setRequestLocale: vi.fn(),
}));

vi.mock("@/components/admin-coming-soon", () => ({
  AdminComingSoon: ({ section }: { section: string }) => (
    <div data-testid="admin-coming-soon">{section}</div>
  ),
}));

const { default: AdminBooksStubPage } = await import("./page");

describe("AdminBooksStubPage", () => {
  it("renders the coming-soon section with the Books sidebar label", async () => {
    render(
      await AdminBooksStubPage({
        params: Promise.resolve({ locale: "en" }),
        searchParams: Promise.resolve({}),
      }),
    );

    expect(screen.getByTestId("admin-coming-soon")).toHaveTextContent("books");
  });
});
