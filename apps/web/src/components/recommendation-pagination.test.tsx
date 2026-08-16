import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `feed-pagination.test.tsx`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
}));

// `RecommendationsPagination` is a Server Component (async function
// returning JSX) — called directly and awaited, same pattern as
// `feed-pagination.test.tsx`.
const { RecommendationsPagination } = await import("./recommendation-pagination");

describe("RecommendationsPagination", () => {
  it("renders nothing on page 1 with no next page", async () => {
    const result = await RecommendationsPagination({ page: 1, hasNext: false });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, preserving the type filter", async () => {
    render(await RecommendationsPagination({ type: "movie", page: 2, hasNext: true }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/recommendations", query: { type: "movie" } }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/recommendations", query: { type: "movie", page: "3" } }),
    );
  });

  it("omits the type query param when no filter is selected", async () => {
    render(await RecommendationsPagination({ page: 1, hasNext: true }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/recommendations", query: { page: "2" } }),
    );
  });

  it("only renders a previous link when there is no next page", async () => {
    render(await RecommendationsPagination({ page: 2, hasNext: false }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/recommendations", query: {} }),
    );
  });
});
