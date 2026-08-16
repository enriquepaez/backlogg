import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `@/i18n/navigation`'s `Link` doesn't resolve under plain Vitest/jsdom (see
// `catalog-section.test.tsx` for the same mock + rationale) — needed here
// since `ItemSimilar` renders `CatalogCard`s with an `href` (FE-10).
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => (
    <a href={href} {...props} />
  ),
}));

const { ItemSimilar } = await import("./item-similar");

describe("ItemSimilar", () => {
  it("renders the heading", () => {
    render(
      <ItemSimilar
        type="movie"
        items={[]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "You might also like" }),
    ).toBeInTheDocument();
  });

  it("renders the empty message when there are no similar items", () => {
    render(
      <ItemSimilar
        type="movie"
        items={[]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(screen.getByText("No similar titles yet.")).toBeInTheDocument();
  });

  it("renders each similar item as a card linking to its own detail page", () => {
    render(
      <ItemSimilar
        type="movie"
        items={[
          {
            title: "Arrival",
            slug: "arrival-2016",
            poster_url: "https://image.tmdb.org/t/p/w500/arrival.jpg",
            release_date: "2016-11-11",
            rating_external: 7.9,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(screen.getByText("Arrival")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/movie/arrival-2016");
    expect(screen.queryByText("No similar titles yet.")).not.toBeInTheDocument();
  });

  it("builds series hrefs under /series/{slug}", () => {
    render(
      <ItemSimilar
        type="series"
        items={[
          {
            title: "The Last of Us",
            slug: "the-last-of-us",
            poster_url: null,
            release_date: "2023-01-15",
            rating_external: 8.7,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "/series/the-last-of-us");
  });

  it("builds book hrefs under /book/{slug}", () => {
    render(
      <ItemSimilar
        type="book"
        items={[
          {
            title: "Dune Messiah",
            slug: "OL893416W",
            poster_url: null,
            release_date: "1969-10-01",
            rating_external: 4.1,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "/book/OL893416W");
  });

  it("builds game hrefs under /game/{slug}", () => {
    render(
      <ItemSimilar
        type="game"
        items={[
          {
            title: "Bastion",
            slug: "bastion",
            poster_url: null,
            release_date: "2011-07-20",
            rating_external: 8.7,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "/game/bastion");
  });
});
