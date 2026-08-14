import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `profile-reviews-pagination.test.tsx`.
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

// `FollowPagination` is a Server Component (async function returning JSX) —
// called directly and awaited, same pattern as `profile-reviews-pagination.test.tsx`.
const { FollowPagination } = await import("./follow-pagination");

describe("FollowPagination", () => {
  it("renders nothing when there is only one page", async () => {
    const result = await FollowPagination({ href: "/u/alice/followers", page: 1, totalPages: 1 });

    expect(result).toBeNull();
  });

  it("renders both prev and next links on a middle page, against the given href", async () => {
    render(await FollowPagination({ href: "/u/alice/following", page: 2, totalPages: 3 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/following", query: {} }),
    );
    expect(links[1]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/following", query: { page: "3" } }),
    );
  });

  it("only renders a next link on page 1", async () => {
    render(await FollowPagination({ href: "/u/alice/followers", page: 1, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/followers", query: { page: "2" } }),
    );
  });

  it("only renders a previous link on the last page", async () => {
    render(await FollowPagination({ href: "/u/alice/followers", page: 2, totalPages: 2 }));

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/u/alice/followers", query: {} }),
    );
  });
});
