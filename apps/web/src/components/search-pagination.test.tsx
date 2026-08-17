import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `browse-pagination.test.tsx`.
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

const { SearchPagination } = await import("./search-pagination");

describe("SearchPagination", () => {
  it("renders nothing when there is only one page", async () => {
    const result = await SearchPagination({ query: "dune", page: 1, totalPages: 1 });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, preserving q/type", async () => {
    render(
      await SearchPagination({ query: "dune", type: "movie", page: 2, totalPages: 3 }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/search", query: { q: "dune", type: "movie" } }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/search",
        query: { q: "dune", type: "movie", page: "3" },
      }),
    );
  });

  it("only renders a next link on page 1, omitting type when unset", async () => {
    render(await SearchPagination({ query: "dune", page: 1, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/search", query: { q: "dune", page: "2" } }),
    );
  });

  it("only renders a previous link on the last page", async () => {
    render(await SearchPagination({ query: "dune", page: 2, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/search", query: { q: "dune" } }),
    );
  });

  // Re-scope of FE-35 (`browse_search_filters`): the date-range and
  // external-rating-range filters must survive pagination the same way
  // `q`/`type` already do.
  it("preserves the date-range and external-rating-range filters in both links", async () => {
    render(
      await SearchPagination({
        query: "dune",
        type: "movie",
        page: 2,
        totalPages: 3,
        dateFrom: "2020-01-01",
        dateTo: "2021-12-31",
        ratingExternalMin: 6.5,
        ratingExternalMax: 9,
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/search",
        query: {
          q: "dune",
          type: "movie",
          date_from: "2020-01-01",
          date_to: "2021-12-31",
          rating_external_min: "6.5",
          rating_external_max: "9",
        },
      }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/search",
        query: {
          q: "dune",
          type: "movie",
          date_from: "2020-01-01",
          date_to: "2021-12-31",
          rating_external_min: "6.5",
          rating_external_max: "9",
          page: "3",
        },
      }),
    );
  });

  it("omits the q param entirely for a filters-only search (no query text)", async () => {
    render(
      await SearchPagination({
        query: "",
        page: 1,
        totalPages: 2,
        dateFrom: "2020-01-01",
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/search", query: { date_from: "2020-01-01", page: "2" } }),
    );
  });
});
