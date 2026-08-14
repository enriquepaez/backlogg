import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `follow-pagination.test.tsx`.
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

// `FeedPagination` is a Server Component (async function returning JSX) —
// called directly and awaited, same pattern as `follow-pagination.test.tsx`.
const { FeedPagination } = await import("./feed-pagination");

describe("FeedPagination", () => {
  it("renders nothing when there is only one page", async () => {
    const result = await FeedPagination({ tab: "following", page: 1, totalPages: 1 });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, preserving a non-default tab", async () => {
    render(await FeedPagination({ tab: "popular", page: 2, totalPages: 3 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/feed", query: { tab: "popular" } }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/feed", query: { tab: "popular", page: "3" } }),
    );
  });

  it("omits the tab query param for the default (following) tab", async () => {
    render(await FeedPagination({ tab: "following", page: 1, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/feed", query: { page: "2" } }),
    );
  });

  it("only renders a previous link on the last page", async () => {
    render(await FeedPagination({ tab: "following", page: 2, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", JSON.stringify({ pathname: "/feed", query: {} }));
  });
});
