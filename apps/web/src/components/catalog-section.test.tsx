import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `@/i18n/navigation`'s `Link` (next-intl's App Router navigation) doesn't
// resolve under plain Vitest/jsdom (it pulls in `next/navigation`'s
// client-only build outside of the Next.js bundler) — mocked here to a
// plain anchor so this stays a focused presentational test, same rationale
// as mocking `@/lib/auth/session` in `src/lib/catalog.test.ts`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => (
    <a href={href} {...props} />
  ),
}));

const { CatalogSection } = await import("./catalog-section");

describe("CatalogSection", () => {
  it("renders children in the non-empty state", () => {
    render(
      <CatalogSection heading="Movies" isEmpty={false} emptyMessage="Empty">
        <p>a card</p>
      </CatalogSection>,
    );

    expect(screen.getByRole("heading", { name: "Movies" })).toBeInTheDocument();
    expect(screen.getByText("a card")).toBeInTheDocument();
    expect(screen.queryByText("Empty")).not.toBeInTheDocument();
  });

  it("renders the empty message instead of children when isEmpty", () => {
    render(
      <CatalogSection heading="Movies" isEmpty emptyMessage="Nothing here">
        <p>a card</p>
      </CatalogSection>,
    );

    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.queryByText("a card")).not.toBeInTheDocument();
  });

  it("renders the view-all link when both href and label are given", () => {
    render(
      <CatalogSection
        heading="Movies"
        isEmpty={false}
        emptyMessage="Empty"
        viewAllHref="/browse/movie"
        viewAllLabel="View all Movies"
      >
        <p>a card</p>
      </CatalogSection>,
    );

    const link = screen.getByRole("link", { name: "View all Movies" });
    expect(link).toHaveAttribute("href", "/browse/movie");
  });

  it("omits the view-all link when not given", () => {
    render(
      <CatalogSection heading="Trending" isEmpty={false} emptyMessage="Empty">
        <p>a card</p>
      </CatalogSection>,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
