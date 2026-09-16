import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CatalogType } from "@/lib/catalog-types";

// `@/i18n/navigation`'s `Link` doesn't resolve under plain Vitest/jsdom (see
// `catalog-section.test.tsx` for the same mock + rationale) — needed here
// since `ItemSimilar` renders `CatalogCard`s with an `href` (FE-10).
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => (
    <a href={href} {...props} />
  ),
}));

const { ItemSimilar } = await import("./item-similar");

/** The four badge labels the page hands down, pre-translated (`Home.typeBadge.*`). */
const typeLabels: Record<CatalogType, string> = {
  movie: "Movie",
  series: "Series",
  book: "Book",
  game: "Game",
};

describe("ItemSimilar", () => {
  it("renders the heading", () => {
    render(
      <ItemSimilar
        items={[]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "You might also like" }),
    ).toBeInTheDocument();
  });

  it("renders the empty message when there are no similar items", () => {
    render(
      <ItemSimilar
        items={[]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(screen.getByText("No similar titles yet.")).toBeInTheDocument();
  });

  it("renders each similar item as a card linking to its own detail page", () => {
    render(
      <ItemSimilar
        items={[
          {
            type: "movie",
            title: "Arrival",
            slug: "arrival-2016",
            poster_url: "https://image.tmdb.org/t/p/w500/arrival.jpg",
            release_date: "2016-11-11",
            rating_internal: 7.9,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(screen.getByText("Arrival")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/movie/arrival-2016");
    expect(screen.queryByText("No similar titles yet.")).not.toBeInTheDocument();
  });

  it("colors the type badge with the type-specific token (FE-57)", () => {
    render(
      <ItemSimilar
        items={[
          {
            type: "movie",
            title: "Arrival",
            slug: "arrival-2016",
            poster_url: null,
            release_date: "2016-11-11",
            rating_internal: 7.9,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(screen.getByText("Movie")).toHaveClass("bg-type-movie", "text-type-movie-foreground");
  });

  it.each([
    ["series", "the-last-of-us", "/series/the-last-of-us"],
    ["book", "OL893416W", "/book/OL893416W"],
    ["game", "bastion", "/game/bastion"],
  ] as const)("builds %s hrefs under its own route segment", (type, slug, href) => {
    render(
      <ItemSimilar
        items={[
          {
            type,
            title: "Whatever",
            slug,
            poster_url: null,
            release_date: "2023-01-15",
            rating_internal: 8.7,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", href);
  });

  /**
   * FE-67, the acceptance criterion this whole feature exists for: with
   * `SIMILAR_CROSS_TYPE_QUOTA = 3` a film's grid holds books, series and
   * games, and each of them must link under **its own** route segment and
   * wear **its own** badge color. Before this feature every card took the
   * type of the *page*, so a book among films was `/movie/{book-slug}` —
   * issues #32/#33/#36 all over again, which is why the backend shipped the
   * quota off until this landed.
   */
  describe("a mixed response (the cross-type quota, FE-67)", () => {
    const mixed = [
      {
        type: "movie" as const,
        title: "The Return of the King",
        slug: "the-lord-of-the-rings-the-return-of-the-king-2003",
        poster_url: null,
        release_date: "2003-12-17",
        rating_internal: 8.9,
      },
      {
        type: "book" as const,
        title: "The Two Towers",
        slug: "OL27479W",
        poster_url: null,
        release_date: "1954-11-11",
        rating_internal: 4.3,
      },
      {
        type: "series" as const,
        title: "The Rings of Power",
        slug: "the-lord-of-the-rings-the-rings-of-power-2022",
        poster_url: null,
        release_date: "2022-09-01",
        rating_internal: 6.9,
      },
      {
        type: "game" as const,
        title: "Shadow of Mordor",
        slug: "middle-earth-shadow-of-mordor",
        poster_url: null,
        release_date: "2014-09-30",
        rating_internal: 8.1,
      },
    ];

    const renderMixed = () =>
      render(
        <ItemSimilar
          items={mixed}
          heading="You might also like"
          emptyMessage="No similar titles yet."
          typeLabels={typeLabels}
        />,
      );

    it("links every result under its own type's route, not the page's", () => {
      renderMixed();

      expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
        "/movie/the-lord-of-the-rings-the-return-of-the-king-2003",
        "/book/OL27479W",
        "/series/the-lord-of-the-rings-the-rings-of-power-2022",
        "/game/middle-earth-shadow-of-mordor",
      ]);
    });

    it("labels and colors each badge from that result's own type (FE-57 tokens)", () => {
      renderMixed();

      const links = screen.getAllByRole("link");
      const expected = [
        ["Movie", "bg-type-movie", "text-type-movie-foreground"],
        ["Book", "bg-type-book", "text-type-book-foreground"],
        ["Series", "bg-type-series", "text-type-series-foreground"],
        ["Game", "bg-type-game", "text-type-game-foreground"],
      ] as const;

      expected.forEach(([label, bg, fg], index) => {
        expect(within(links[index]).getByText(label)).toHaveClass(bg, fg);
      });
    });

    it("keeps the backend's order — a cross-type result is not grouped or moved", () => {
      renderMixed();

      expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
        expect.stringContaining("The Return of the King"),
        expect.stringContaining("The Two Towers"),
        expect.stringContaining("The Rings of Power"),
        expect.stringContaining("Shadow of Mordor"),
      ]);
    });

    it("renders no extra section or heading for the cross-type results", () => {
      const { container } = renderMixed();

      expect(container.querySelectorAll("section")).toHaveLength(1);
      expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
    });

    /**
     * A film and the novel it comes from routinely share a slug, and this
     * grid can now hold both at once — so the React `key` has to include the
     * type. The `href`s alone do NOT prove that (they render fine with a
     * duplicated key), so the assertion that actually pins the `key` is the
     * absence of React's duplicate-key report, which it emits through
     * `console.error` and nowhere else. Mutating the component to
     * `key={item.slug}` must fail this test.
     */
    it("keeps two same-slug items of different types apart (the key includes the type)", () => {
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

      try {
        render(
          <ItemSimilar
            items={[
              {
                type: "movie" as const,
                title: "Dune",
                slug: "dune",
                poster_url: null,
                release_date: "2021-10-22",
                rating_internal: 8.0,
              },
              {
                type: "book" as const,
                title: "Dune",
                slug: "dune",
                poster_url: null,
                release_date: "1965-08-01",
                rating_internal: 4.2,
              },
            ]}
            heading="You might also like"
            emptyMessage="No similar titles yet."
            typeLabels={typeLabels}
          />,
        );

        // Matched on the stable part of React's wording ("two children with
        // the same key"), not on the whole sentence, so a reworded warning in
        // a future React still trips this.
        const duplicateKeyReports = consoleError.mock.calls.filter((call) =>
          call.some(
            (arg) => typeof arg === "string" && arg.includes("two children with the same key"),
          ),
        );

        expect(duplicateKeyReports).toEqual([]);
      } finally {
        consoleError.mockRestore();
      }

      expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
        "/movie/dune",
        "/book/dune",
      ]);
    });
  });

  /**
   * The other half of FE-67's acceptance: a same-type-only response — what
   * the backend still serves for any item without a vector, and what every
   * item served while the quota was 0 — must look exactly as it did before
   * this feature. No empty slot, no "also in other media" placeholder.
   */
  it("behaves exactly as before when the response holds no cross-type item", () => {
    const { container } = render(
      <ItemSimilar
        items={[
          {
            type: "movie",
            title: "Arrival",
            slug: "arrival-2016",
            poster_url: null,
            release_date: "2016-11-11",
            rating_internal: 7.9,
          },
          {
            type: "movie",
            title: "Sicario",
            slug: "sicario-2015",
            poster_url: null,
            release_date: "2015-09-18",
            rating_internal: 7.6,
          },
        ]}
        heading="You might also like"
        emptyMessage="No similar titles yet."
        typeLabels={typeLabels}
      />,
    );

    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(container.querySelectorAll("section")).toHaveLength(1);
    expect(screen.getAllByText("Movie")).toHaveLength(2);
    expect(screen.queryByText("Series")).not.toBeInTheDocument();
    expect(screen.queryByText("No similar titles yet.")).not.toBeInTheDocument();
  });
});
