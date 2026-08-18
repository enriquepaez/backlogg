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

// `LibraryPagination` is a Server Component (async function returning JSX) —
// called directly and awaited, same pattern as `browse-pagination.test.tsx`.
const { LibraryPagination } = await import("./library-pagination");

describe("LibraryPagination", () => {
  it("renders nothing when there is only one page", async () => {
    const result = await LibraryPagination({
      username: "alice",
      page: 1,
      totalPages: 1,
    });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, preserving status/type", async () => {
    render(
      await LibraryPagination({
        username: "alice",
        status: "completed",
        type: "movie",
        page: 2,
        totalPages: 3,
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/u/alice/library",
        query: { status: "completed", type: "movie" },
      }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({
        pathname: "/u/alice/library",
        query: { status: "completed", type: "movie", page: "3" },
      }),
    );
  });

  it("includes a non-default sort in the query and omits the default one", async () => {
    render(
      await LibraryPagination({
        username: "alice",
        sort: "title_asc",
        page: 1,
        totalPages: 2,
      }),
    );

    expect(screen.getAllByRole("link")[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/library", query: { sort: "title_asc", page: "2" } }),
    );
  });

  it("omits sort from the query when it's the default (updated_desc)", async () => {
    render(
      await LibraryPagination({
        username: "alice",
        sort: "updated_desc",
        page: 1,
        totalPages: 2,
      }),
    );

    expect(screen.getAllByRole("link")[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/library", query: { page: "2" } }),
    );
  });

  it("only renders a next link on page 1, omitting status/type when unset", async () => {
    render(
      await LibraryPagination({
        username: "alice",
        page: 1,
        totalPages: 2,
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/library", query: { page: "2" } }),
    );
  });

  it("only renders a previous link on the last page", async () => {
    render(
      await LibraryPagination({
        username: "alice",
        page: 2,
        totalPages: 2,
      }),
    );

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/library", query: {} }),
    );
  });
});
