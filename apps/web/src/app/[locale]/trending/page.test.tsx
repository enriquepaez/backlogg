import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Namespace-prefixed echo, same approach as `search/page.test.tsx`: this page
// reads from two namespaces (`Trending` for its own copy, `Home` for the type
// badge), so the prefix is what tells them apart.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => (key: string) => `${namespace}:${key}`,
  setRequestLocale: vi.fn(),
}));

// `@/lib/catalog` transitively imports `server-only` (via `@/lib/auth/session`),
// which Vitest can't resolve outside a Next.js build — so it's mocked. Only
// the network call is faked: the vocabulary (`trendingItemType`,
// `isCatalogType`, `DEFAULT_TRENDING_PERIOD`) comes from the REAL
// framework-agnostic `@/lib/catalog-types`, because the item_type → route
// mapping is exactly what these tests are here to pin down (issue #32).
const getTrendingPage = vi.fn();
vi.mock("@/lib/catalog", async () => {
  const catalogTypes = await import("@/lib/catalog-types");
  return {
    ...catalogTypes,
    getTrendingPage: (options: unknown) => getTrendingPage(options),
  };
});

// `TrendingFilters` is a Client Component with its own test suite; `CatalogCard`
// likewise. Stubbed to expose their props, same rationale as
// `search/page.test.tsx`.
vi.mock("@/components/trending-filters", () => ({
  TrendingFilters: (props: Record<string, unknown>) => (
    <div data-testid="trending-filters" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/catalog-card", () => ({
  CatalogCard: (props: Record<string, unknown>) => (
    <div data-testid="catalog-card" data-props={JSON.stringify(props)} />
  ),
}));

const { default: TrendingPage } = await import("./page");

type TrendingItemFixture = {
  item_type: string;
  title: string;
  slug: string;
  poster_url: string | null;
  release_date: string | null;
  rating_external: number | null;
  rating_internal: number | null;
};

function trendingItem(item_type: string, slug: string): TrendingItemFixture {
  return {
    item_type,
    title: slug,
    slug,
    poster_url: null,
    release_date: null,
    rating_external: null,
    rating_internal: null,
  };
}

const ALL_TYPES = [
  trendingItem("MOVIE", "dune-2021"),
  trendingItem("SERIES", "chernobyl"),
  trendingItem("BOOK", "un-cuento-perfecto-2020"),
  trendingItem("GAME", "escape-from-tarkov"),
];

function renderPage(searchParams: Record<string, string> = {}) {
  return TrendingPage({
    params: Promise.resolve({ locale: "en" }),
    searchParams: Promise.resolve(searchParams),
  });
}

function cards() {
  return screen
    .getAllByTestId("catalog-card")
    .map((node) => JSON.parse(node.dataset.props ?? "{}") as Record<string, unknown>);
}

beforeEach(() => {
  getTrendingPage.mockReset();
  getTrendingPage.mockResolvedValue({ ok: true, results: ALL_TYPES });
});

describe("TrendingPage type mapping (issue #32)", () => {
  it("links every card to its own type's route, never collapsing to movie/series", async () => {
    render(await renderPage());

    expect(cards().map((card) => card.href)).toEqual([
      "/movie/dune-2021",
      "/series/chernobyl",
      "/book/un-cuento-perfecto-2020",
      "/game/escape-from-tarkov",
    ]);
  });

  it("links a book to /book/{slug} and a game to /game/{slug}", async () => {
    // The exact regression: before FE-68 both of these rendered as
    // `/series/{slug}`, which in production resolved to a *different, real*
    // series ("A Perfect Story", "Escape from Tarkov. Raid.").
    render(await renderPage());

    const hrefs = cards().map((card) => card.href);
    expect(hrefs).toContain("/book/un-cuento-perfecto-2020");
    expect(hrefs).toContain("/game/escape-from-tarkov");
    expect(hrefs).not.toContain("/series/un-cuento-perfecto-2020");
    expect(hrefs).not.toContain("/series/escape-from-tarkov");
  });

  it("badges each card with its own type label", async () => {
    render(await renderPage());

    expect(cards().map((card) => card.typeLabel)).toEqual([
      "Home:typeBadge.movie",
      "Home:typeBadge.series",
      "Home:typeBadge.book",
      "Home:typeBadge.game",
    ]);
    expect(cards().map((card) => card.itemType)).toEqual([
      "movie",
      "series",
      "book",
      "game",
    ]);
  });

  it("skips an item whose item_type has no route instead of linking it wrong", async () => {
    getTrendingPage.mockResolvedValue({
      ok: true,
      results: [trendingItem("PODCAST", "some-podcast"), ...ALL_TYPES],
    });

    render(await renderPage());

    expect(cards()).toHaveLength(4);
    expect(cards().map((card) => card.href)).not.toContain("/series/some-podcast");
  });
});

describe("TrendingPage query params", () => {
  it.each(["movie", "series", "book", "game"])(
    "parses ?type=%s and forwards it to the API client",
    async (type) => {
      await renderPage({ type });

      expect(getTrendingPage).toHaveBeenCalledWith({ type, period: "week" });
    },
  );

  it("forwards type and period together", async () => {
    await renderPage({ type: "game", period: "day" });

    expect(getTrendingPage).toHaveBeenCalledWith({ type: "game", period: "day" });
  });

  it("drops an unknown ?type= and falls back to the unfiltered list", async () => {
    await renderPage({ type: "podcast" });

    expect(getTrendingPage).toHaveBeenCalledWith({ type: undefined, period: "week" });
  });

  it("falls back to the default period for an unknown ?period=", async () => {
    await renderPage({ type: "book", period: "century" });

    expect(getTrendingPage).toHaveBeenCalledWith({ type: "book", period: "week" });
  });

  it("passes the parsed filters down to TrendingFilters", async () => {
    render(await renderPage({ type: "book", period: "day" }));

    expect(
      JSON.parse(screen.getByTestId("trending-filters").dataset.props ?? "{}"),
    ).toEqual({ selectedType: "book", selectedPeriod: "day" });
  });
});

describe("TrendingPage states", () => {
  it("shows the error message when the fetch fails", async () => {
    getTrendingPage.mockResolvedValue({ ok: false });

    render(await renderPage());

    expect(screen.getByRole("alert")).toHaveTextContent("Trending:error");
    expect(screen.queryAllByTestId("catalog-card")).toHaveLength(0);
  });

  it("shows the empty message when there are no results", async () => {
    getTrendingPage.mockResolvedValue({ ok: true, results: [] });

    render(await renderPage());

    expect(screen.getByText("Trending:empty")).toBeInTheDocument();
  });
});
