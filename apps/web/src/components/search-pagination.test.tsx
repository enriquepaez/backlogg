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
});
