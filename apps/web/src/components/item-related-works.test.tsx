import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `@/i18n/navigation`'s `Link` doesn't resolve under plain Vitest/jsdom (see
// `catalog-section.test.tsx` for the same mock + rationale) — needed here
// since every entry is a `CatalogCard` with an `href`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));

// Type-only import: erased at compile time, so it doesn't defeat the
// `vi.mock` hoisting the runtime `await import` below works around.
import type { ItemRelatedWork as RelatedWork } from "./item-related-works";

const { ItemRelatedWorks } = await import("./item-related-works");

/** `Home.typeBadge.*` as resolved against `messages/en.json`. */
const typeLabels = {
  movie: "Movie",
  series: "Series",
  book: "Book",
  game: "Game",
} as const;

/**
 * What the page passes as `directionLabels`
 * (`relatedWorkDirectionLabels(t, item.title)`), resolved against
 * `messages/en.json` for a page whose item is *Better Call Saul* — the real
 * dev-catalog item that carries both directions at once.
 */
const directionLabels = {
  SOURCE: "Better Call Saul is based on this work",
  DERIVED: "Derived from Better Call Saul",
} as const;

function renderSection(items: RelatedWork[]) {
  return render(
    <ItemRelatedWorks
      items={items}
      heading="Related works"
      typeLabels={typeLabels}
      directionLabels={directionLabels}
    />,
  );
}

describe("ItemRelatedWorks", () => {
  it("renders the heading when there is at least one related work", () => {
    renderSection([
      {
        type: "series",
        slug: "breaking-bad-2008",
        title: "Breaking Bad",
        poster_url: null,
        direction: "SOURCE",
      },
    ]);

    expect(screen.getByRole("heading", { level: 2, name: "Related works" })).toBeInTheDocument();
  });

  // FE-66 acceptance: "un ítem sin adaptaciones no renderiza la sección —
  // sin encabezado vacío ni placeholder". The common case, not an edge one:
  // most of the catalog has no declared edge at all.
  it("renders absolutely nothing — no heading, no placeholder — when there are no related works", () => {
    const { container } = renderSection([]);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("heading", { name: "Related works" })).not.toBeInTheDocument();
  });

  it("renders nothing instead of crashing when items arrives undefined (malformed/degraded data)", () => {
    const { container } = render(
      <ItemRelatedWorks
        items={undefined as unknown as RelatedWork[]}
        heading="Related works"
        typeLabels={typeLabels}
        directionLabels={directionLabels}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  /**
   * The load-bearing case: two different types **and** both directions in
   * one response. Mirrors what the dev DB actually serves — a series page
   * whose source is another series (16 of the 18 edges are
   * `SERIES`→`SERIES`), a derived series, and a cross-media book.
   */
  const mixed: RelatedWork[] = [
    {
      type: "series",
      slug: "breaking-bad-2008",
      title: "Breaking Bad",
      poster_url: "https://image.tmdb.org/t/p/w500/bb.jpg",
      direction: "SOURCE",
    },
    {
      type: "series",
      slug: "slippin-jimmy-2022",
      title: "Better Call Saul Presents: Slippin' Jimmy",
      poster_url: null,
      direction: "DERIVED",
    },
    {
      type: "book",
      slug: "the-handmaids-tale-1985",
      title: "The Handmaid's Tale",
      poster_url: null,
      direction: "SOURCE",
    },
  ];

  it("lists every entry with its title, whatever its type or direction", () => {
    renderSection(mixed);

    expect(screen.getByText("Breaking Bad")).toBeInTheDocument();
    expect(
      screen.getByText("Better Call Saul Presents: Slippin' Jimmy"),
    ).toBeInTheDocument();
    expect(screen.getByText("The Handmaid's Tale")).toBeInTheDocument();
  });

  // FE-66 acceptance: "las dos direcciones de la relación se distinguen en
  // el texto (origen vs obra derivada), no se presentan como una lista
  // indiferenciada".
  it("spells out each entry's direction in its own text, never leaving it to the ordering", () => {
    renderSection(mixed);

    // Two `SOURCE` entries, one `DERIVED` — each carrying its own sentence.
    expect(screen.getAllByText(directionLabels.SOURCE)).toHaveLength(2);
    expect(screen.getAllByText(directionLabels.DERIVED)).toHaveLength(1);
    expect(directionLabels.SOURCE).not.toBe(directionLabels.DERIVED);
    // And the sentence sits on the right card, not merely somewhere on the
    // page: the derived one belongs to the spin-off.
    const derivedLink = screen.getByRole("link", {
      name: /Slippin' Jimmy/,
    });
    expect(derivedLink).toHaveTextContent(directionLabels.DERIVED);
    expect(derivedLink).not.toHaveTextContent(directionLabels.SOURCE);
  });

  // The single highest-risk behaviour of this feature (issues #32/#33/#36):
  // the related item's type is routinely *different* from the page's, so the
  // href must follow the entry's own type.
  it("links each entry under the related item's own type, not the page's", () => {
    renderSection(mixed);

    expect(screen.getByRole("link", { name: /Breaking Bad/ })).toHaveAttribute(
      "href",
      "/series/breaking-bad-2008",
    );
    expect(screen.getByRole("link", { name: /Slippin' Jimmy/ })).toHaveAttribute(
      "href",
      "/series/slippin-jimmy-2022",
    );
    expect(screen.getByRole("link", { name: /The Handmaid's Tale/ })).toHaveAttribute(
      "href",
      "/book/the-handmaids-tale-1985",
    );
  });

  it.each([
    ["movie", "/movie/dune-1984"],
    ["series", "/series/dune-1984"],
    ["book", "/book/dune-1984"],
    ["game", "/game/dune-1984"],
  ] as const)("builds a %s entry's href under its own route segment", (type, href) => {
    renderSection([
      { type, slug: "dune-1984", title: "Dune", poster_url: null, direction: "SOURCE" },
    ]);

    expect(screen.getByRole("link")).toHaveAttribute("href", href);
  });

  // FE-57's `TYPE_COLOR_CLASSES`, reused rather than reinvented: the color
  // of the badge is the only thing that makes a cross-media entry stand out
  // in this single, neutrally-titled section.
  it("badges each entry with its own type, colored with the FE-57 type token", () => {
    renderSection(mixed);

    expect(screen.getAllByText("Series")).toHaveLength(2);
    for (const badge of screen.getAllByText("Series")) {
      expect(badge).toHaveClass("bg-type-series", "text-type-series-foreground");
    }
    expect(screen.getByText("Book")).toHaveClass("bg-type-book", "text-type-book-foreground");
  });

  it("shows no rating badge — this section is about a declared relation, not about scores", () => {
    renderSection(mixed);

    // The endpoint carries no rating, so every card gets
    // `ratingInternal: null` and `CatalogCard` omits its chip entirely (same
    // assertion that component's own suite uses).
    expect(screen.queryByText(/\d\.\d/)).not.toBeInTheDocument();
  });
});
