import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `catalog-section.test.tsx`/`browse-filters.test.tsx`:
// `@/i18n/navigation`'s `Link` doesn't resolve under plain Vitest/jsdom, and
// `next-intl/server`'s `getTranslations` needs a request context this test
// doesn't set up. `Link`'s mock serializes an object `href` (this component
// passes `{ pathname, query }`) to JSON so assertions can inspect it.
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

// `BrowsePagination` is a Server Component (async function returning JSX) —
// called directly and awaited rather than rendered as `<BrowsePagination />`,
// same pattern as testing any other async function; the resolved element is
// then handed to Testing Library like any other React tree.
const { BrowsePagination } = await import("./browse-pagination");

describe("BrowsePagination", () => {
  it("renders nothing when there is only one page", async () => {
    const result = await BrowsePagination({
      type: "movie",
      page: 1,
      totalPages: 1,
      sort: "rating_desc",
    });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, preserving genre/sort", async () => {
    render(
      await BrowsePagination({
        type: "movie",
        page: 2,
        totalPages: 3,
        genre: "drama",
        sort: "date_desc",
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/browse/movie",
        query: { genre: "drama", sort: "date_desc" },
      }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/browse/movie",
        query: { genre: "drama", sort: "date_desc", page: "3" },
      }),
    );
  });

  it("only renders a next link on page 1, omitting the default sort from the query", async () => {
    render(
      await BrowsePagination({
        type: "movie",
        page: 1,
        totalPages: 2,
        sort: "rating_desc",
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/browse/movie", query: { page: "2" } }),
    );
  });

  it("only renders a previous link on the last page", async () => {
    render(
      await BrowsePagination({
        type: "movie",
        page: 2,
        totalPages: 2,
        sort: "rating_desc",
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/browse/movie", query: {} }),
    );
  });
});
