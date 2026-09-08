import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Key echo, same approach as `search/page.test.tsx` (single namespace here,
// so no prefix needed).
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}:${JSON.stringify(vars)}` : key,
  setRequestLocale: vi.fn(),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// Only the network calls are faked; the real `trendingItemType` (from the
// `server-only`-free `@/lib/catalog-types`) is what these tests exercise.
// Same mocking rationale as `trending/page.test.tsx`.
const getTrending = vi.fn();
const getAllFeatured = vi.fn();
vi.mock("@/lib/catalog", async () => {
  const catalogTypes = await import("@/lib/catalog-types");
  return {
    ...catalogTypes,
    getTrending: () => getTrending(),
    getAllFeatured: () => getAllFeatured(),
  };
});

vi.mock("@/components/catalog-card", () => ({
  CatalogCard: (props: Record<string, unknown>) => (
    <div data-testid="catalog-card" data-props={JSON.stringify(props)} />
  ),
}));

const { default: Home } = await import("./page");

/** The home route takes no query params, but `PageProps` still requires the key. */
function renderPage() {
  return Home({
    params: Promise.resolve({ locale: "en" }),
    searchParams: Promise.resolve({}),
  });
}

function trendingItem(item_type: string, slug: string) {
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

beforeEach(() => {
  getTrending.mockReset();
  getAllFeatured.mockReset();
  getTrending.mockResolvedValue([
    trendingItem("MOVIE", "dune-2021"),
    trendingItem("SERIES", "chernobyl"),
    trendingItem("BOOK", "un-cuento-perfecto-2020"),
    trendingItem("GAME", "escape-from-tarkov"),
  ]);
  // The four "featured" sections are out of scope here.
  getAllFeatured.mockResolvedValue({ movie: [], series: [], book: [], game: [] });
});

function cards() {
  return screen
    .getAllByTestId("catalog-card")
    .map((node) => JSON.parse(node.dataset.props ?? "{}") as Record<string, unknown>);
}

/**
 * The home page's trending section had its own private copy of the
 * item_type → route mapping, so it shipped the same wrong links as
 * `/trending` (issue #32). It now uses the shared `trendingItemType`; this
 * suite makes sure a private copy can't come back unnoticed.
 */
describe("Home trending section (issue #32)", () => {
  it("links each trending card to its own type's route", async () => {
    render(await renderPage());

    expect(cards().map((card) => card.href)).toEqual([
      "/movie/dune-2021",
      "/series/chernobyl",
      "/book/un-cuento-perfecto-2020",
      "/game/escape-from-tarkov",
    ]);
  });

  it("badges books and games as such, not as series", async () => {
    render(await renderPage());

    expect(cards().map((card) => card.typeLabel)).toEqual([
      "typeBadge.movie",
      "typeBadge.series",
      "typeBadge.book",
      "typeBadge.game",
    ]);
  });

  it("skips an item whose item_type has no route", async () => {
    getTrending.mockResolvedValue([
      trendingItem("PODCAST", "some-podcast"),
      trendingItem("BOOK", "un-cuento-perfecto-2020"),
    ]);

    render(await renderPage());

    expect(cards().map((card) => card.href)).toEqual(["/book/un-cuento-perfecto-2020"]);
  });

  it("shows the empty message when trending has no results", async () => {
    getTrending.mockResolvedValue([]);

    render(await renderPage());

    expect(screen.getAllByText("trendingEmpty")).not.toHaveLength(0);
    expect(screen.queryAllByTestId("catalog-card")).toHaveLength(0);
  });
});
