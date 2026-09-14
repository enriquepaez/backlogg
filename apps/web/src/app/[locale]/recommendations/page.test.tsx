import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Namespace-prefixed echo, same approach as `trending/page.test.tsx`: this
// page reads from two namespaces (`Recommendations` for its own copy, `Home`
// for the type badge), so the prefix is what tells them apart.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => (key: string) => `${namespace}:${key}`,
  setRequestLocale: vi.fn(),
}));

const redirect = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  redirect: (options: unknown) => redirect(options),
}));

// `@/lib/recommendations` and `@/lib/api-fetch` transitively import
// `server-only` (via `@/lib/auth/session`), which Vitest can't resolve
// outside a Next.js build — so both are mocked. Only the network calls are
// faked: the item_type → route mapping comes from the REAL,
// `server-only`-free `@/lib/catalog-types`, because that mapping is exactly
// what this suite is here to pin down (issue #33). Same rationale as
// `trending/page.test.tsx`.
const getRecommendations = vi.fn();
vi.mock("@/lib/recommendations", () => ({
  RECOMMENDATIONS_FALLBACK_REASON: "Popular right now",
  getRecommendations: (query: unknown) => getRecommendations(query),
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

// `RecommendationFilters`/`RecommendationsPagination`/`CatalogCard` are
// components with their own tests; stubbed to expose their props, same
// rationale as `trending/page.test.tsx`.
vi.mock("@/components/recommendation-filters", () => ({
  RecommendationFilters: (props: Record<string, unknown>) => (
    <div data-testid="recommendation-filters" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/recommendation-pagination", () => ({
  RecommendationsPagination: (props: Record<string, unknown>) => (
    <div data-testid="recommendations-pagination" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/catalog-card", () => ({
  CatalogCard: (props: Record<string, unknown>) => (
    <div data-testid="catalog-card" data-props={JSON.stringify(props)} />
  ),
}));

const { default: RecommendationsPage } = await import("./page");

type RecommendationFixture = {
  item_type: string;
  title: string;
  slug: string;
  poster_url: string | null;
  release_date: string | null;
  rating_external: number | null;
  rating_internal: number | null;
  reason: string;
};

function recommendation(item_type: string, slug: string): RecommendationFixture {
  return {
    item_type,
    title: slug,
    slug,
    poster_url: null,
    release_date: null,
    rating_external: null,
    rating_internal: null,
    reason: `Because you rated ${slug}`,
  };
}

const ALL_TYPES = [
  recommendation("MOVIE", "dune-2021"),
  recommendation("SERIES", "chernobyl"),
  recommendation("BOOK", "un-cuento-perfecto-2020"),
  recommendation("GAME", "escape-from-tarkov"),
];

function renderPage(searchParams: Record<string, string> = {}) {
  return RecommendationsPage({
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
  getRecommendations.mockReset();
  getCurrentUser.mockReset();
  redirect.mockReset();
  getCurrentUser.mockResolvedValue({ username: "alice" });
  getRecommendations.mockResolvedValue({ ok: true, results: ALL_TYPES, page: 1, limit: 20 });
});

describe("RecommendationsPage type mapping (issue #33)", () => {
  it("links every card to its own type's route", async () => {
    render(await renderPage());

    expect(cards().map((card) => card.href)).toEqual([
      "/movie/dune-2021",
      "/series/chernobyl",
      "/book/un-cuento-perfecto-2020",
      "/game/escape-from-tarkov",
    ]);
    expect(cards().map((card) => card.itemType)).toEqual(["movie", "series", "book", "game"]);
    expect(cards().map((card) => card.typeLabel)).toEqual([
      "Home:typeBadge.movie",
      "Home:typeBadge.series",
      "Home:typeBadge.book",
      "Home:typeBadge.game",
    ]);
  });

  it("skips an item whose item_type has no route instead of linking it wrong", async () => {
    // The issue: `item.item_type.toLowerCase() as CatalogType` turned a
    // fifth backend type into a confident `/podcast/{slug}` link. The card
    // must not be rendered at all now — a missing card is recoverable, a
    // wrong link is not.
    getRecommendations.mockResolvedValue({
      ok: true,
      results: [recommendation("PODCAST", "some-podcast"), ...ALL_TYPES],
      page: 1,
      limit: 20,
    });

    render(await renderPage());

    expect(cards()).toHaveLength(4);
    expect(cards().map((card) => card.href)).not.toContain("/podcast/some-podcast");
    expect(screen.queryByText("Home:typeBadge.undefined")).not.toBeInTheDocument();
  });

  it("renders nothing at all when every result is of an unknown type", async () => {
    // Degenerate case of the above: the grid renders empty rather than a row
    // of broken links, and the page does not crash.
    getRecommendations.mockResolvedValue({
      ok: true,
      results: [recommendation("PODCAST", "some-podcast")],
      page: 1,
      limit: 20,
    });

    render(await renderPage());

    expect(screen.queryAllByTestId("catalog-card")).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("RecommendationsPage query params", () => {
  it.each(["movie", "series", "book", "game"])(
    "parses ?type=%s and forwards it to the API client",
    async (type) => {
      await renderPage({ type });

      expect(getRecommendations).toHaveBeenCalledWith({ type, page: 1, limit: 20 });
    },
  );

  it("drops an unknown ?type= and falls back to the unfiltered list", async () => {
    await renderPage({ type: "podcast" });

    expect(getRecommendations).toHaveBeenCalledWith({ type: undefined, page: 1, limit: 20 });
  });
});

describe("RecommendationsPage states", () => {
  it("redirects to /login when there is no valid session", async () => {
    getCurrentUser.mockResolvedValue(null);

    await renderPage();

    expect(redirect).toHaveBeenCalledWith({ href: "/login", locale: "en" });
    expect(getRecommendations).not.toHaveBeenCalled();
  });

  it("shows the error message when the fetch fails", async () => {
    getRecommendations.mockResolvedValue({ ok: false });

    render(await renderPage());

    expect(screen.getByRole("alert")).toHaveTextContent("Recommendations:error");
    expect(screen.queryAllByTestId("catalog-card")).toHaveLength(0);
  });

  it("shows the empty message when there are no results", async () => {
    getRecommendations.mockResolvedValue({ ok: true, results: [], page: 1, limit: 20 });

    render(await renderPage());

    expect(screen.getByText("Recommendations:empty")).toBeInTheDocument();
  });

  it("shows the no-seeds banner as a status, never as an error", async () => {
    getRecommendations.mockResolvedValue({
      ok: true,
      results: ALL_TYPES.map((item) => ({ ...item, reason: "Popular right now" })),
      page: 1,
      limit: 20,
    });

    render(await renderPage());

    expect(screen.getByRole("status")).toHaveTextContent("Recommendations:fallback");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
