import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `admin/movies/page.test.tsx`: a namespace-agnostic echo
// is enough since `Search`/`Browse` never share a key name in this page.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${namespace}:${key}:${JSON.stringify(vars)}` : `${namespace}:${key}`,
  setRequestLocale: vi.fn(),
}));

// `@/lib/search` can't be `vi.importActual`-ed here: it transitively pulls in
// `server-only` through `@/lib/auth/session` (see that file's own doc
// comment for why), which Vitest can't resolve outside a Next.js build. So
// `toCatalogType` is reimplemented from the framework-agnostic
// `@/lib/catalog-types` (no `server-only` dependency) instead of imported
// from the real module.
const searchCatalog = vi.fn();
vi.mock("@/lib/search", async () => {
  const { isCatalogType } = await import("@/lib/catalog-types");
  return {
    searchCatalog: (query: string, options: unknown) => searchCatalog(query, options),
    toCatalogType: (itemType: string) => {
      const lower = itemType.toLowerCase();
      return isCatalogType(lower) ? lower : undefined;
    },
  };
});

// `SearchControls`/`SearchPagination`/`CatalogCard`/`RateLimitNotice` all
// have their own dedicated tests — out of scope here, same rationale
// `admin/movies/page.test.tsx` uses for mocking `AdminCatalogFilters`/
// `AdminCatalogTable`/`AdminCatalogPagination`. `SearchPagination` (like
// `AdminCatalogPagination`) is itself an async Server Component in real
// code — real ReactDOM (used by `render()` here) can't render an async
// function component directly, so the sync stand-in below is required, not
// just a convenience.
vi.mock("@/components/search-controls", () => ({
  SearchControls: (props: Record<string, unknown>) => (
    <div data-testid="search-controls" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/search-pagination", () => ({
  SearchPagination: (props: Record<string, unknown>) => (
    <div data-testid="search-pagination" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/catalog-card", () => ({
  CatalogCard: (props: Record<string, unknown>) => (
    <div data-testid="catalog-card" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/rate-limit-notice", () => ({
  RateLimitNotice: (props: Record<string, unknown>) => (
    <div data-testid="rate-limit-notice" data-props={JSON.stringify(props)} />
  ),
}));

const { default: SearchPage } = await import("./page");

const resultItem = {
  id: 1,
  item_type: "MOVIE",
  slug: "dune-2021",
  title: "Dune",
  overview: null,
  poster_url: null,
  release_date: "2021-10-22",
  rating_external: 7.8,
  rating_internal: null,
};

beforeEach(() => {
  searchCatalog.mockClear();
});

function renderPage(searchParams: Record<string, string> = {}) {
  return SearchPage({
    params: Promise.resolve({ locale: "en" }),
    searchParams: Promise.resolve(searchParams),
  });
}

describe("SearchPage", () => {
  it("renders the heading", async () => {
    render(await renderPage());

    expect(screen.getByRole("heading", { name: "Search:heading" })).toBeInTheDocument();
  });

  it("shows the empty prompt and never fetches when neither q nor any filter is active", async () => {
    render(await renderPage());

    expect(searchCatalog).not.toHaveBeenCalled();
    expect(screen.getByText("Search:prompt")).toBeInTheDocument();
  });

  it("fetches and forwards q/type/page to searchCatalog", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [resultItem], total: 1, page: 1, limit: 24 });

    await renderPage({ q: "dune", type: "movie", page: "2" });

    expect(searchCatalog).toHaveBeenCalledWith("dune", {
      type: "movie",
      page: 2,
      dateFrom: undefined,
      dateTo: undefined,
      ratingExternalMin: undefined,
      ratingExternalMax: undefined,
    });
  });

  it("fetches with an empty q as soon as a date/rating filter is active", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [resultItem], total: 1, page: 1, limit: 24 });

    await renderPage({ date_from: "2020-01-01" });

    expect(searchCatalog).toHaveBeenCalledWith("", {
      type: undefined,
      page: 1,
      dateFrom: "2020-01-01",
      dateTo: undefined,
      ratingExternalMin: undefined,
      ratingExternalMax: undefined,
    });
  });

  it("parses all four filters from searchParams and forwards them to searchCatalog", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [], total: 0, page: 1, limit: 24 });

    await renderPage({
      q: "dune",
      date_from: "2020-01-01",
      date_to: "2021-12-31",
      rating_external_min: "6.5",
      rating_external_max: "9",
    });

    expect(searchCatalog).toHaveBeenCalledWith("dune", {
      type: undefined,
      page: 1,
      dateFrom: "2020-01-01",
      dateTo: "2021-12-31",
      ratingExternalMin: 6.5,
      ratingExternalMax: 9,
    });
  });

  it("ignores malformed rating searchParams instead of forwarding garbage", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [], total: 0, page: 1, limit: 24 });

    render(await renderPage({ rating_external_min: "not-a-number" }));

    expect(searchCatalog).not.toHaveBeenCalled();
    expect(screen.getByText("Search:prompt")).toBeInTheDocument();
  });

  it("ignores malformed date searchParams instead of forwarding garbage", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [], total: 0, page: 1, limit: 24 });

    const { unmount } = render(await renderPage({ date_from: "not-a-date" }));
    expect(searchCatalog).not.toHaveBeenCalled();
    expect(screen.getByText("Search:prompt")).toBeInTheDocument();
    unmount();

    // Shape-valid but nonexistent calendar date (e.g. month 13, day 45) —
    // same round-trip-through-Date.UTC rejection as `parseIsoDate` in
    // `@/lib/admin-catalog-search-params.ts`.
    render(await renderPage({ date_from: "2024-13-45" }));
    expect(searchCatalog).not.toHaveBeenCalled();
    expect(screen.getByText("Search:prompt")).toBeInTheDocument();
  });

  it("forwards the parsed filters to SearchControls", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [], total: 0, page: 1, limit: 24 });

    render(
      await renderPage({
        q: "dune",
        date_from: "2020-01-01",
        rating_external_min: "6.5",
      }),
    );

    const controls = screen.getByTestId("search-controls");
    const props = JSON.parse(controls.getAttribute("data-props")!);
    expect(props).toMatchObject({
      initialQuery: "dune",
      initialDateFrom: "2020-01-01",
      initialRatingExternalMin: 6.5,
    });
  });

  it("shows an invalid-query message on a 422", async () => {
    searchCatalog.mockResolvedValue({ status: "invalid" });

    render(await renderPage({ q: "dune" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Search:invalidQuery");
  });

  it("shows the rate-limit notice on a 429", async () => {
    searchCatalog.mockResolvedValue({ status: "rate-limited", retryAfterSeconds: 30 });

    render(await renderPage({ q: "dune" }));

    const notice = screen.getByTestId("rate-limit-notice");
    expect(JSON.parse(notice.getAttribute("data-props")!)).toEqual({ retryAfterSeconds: 30 });
  });

  it("shows a generic error message on an unexpected failure", async () => {
    searchCatalog.mockResolvedValue({ status: "error" });

    render(await renderPage({ q: "dune" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Search:error");
  });

  it("shows the empty-results message when the search matches nothing", async () => {
    searchCatalog.mockResolvedValue({ status: "ok", results: [], total: 0, page: 1, limit: 24 });

    render(await renderPage({ q: "no-results" }));

    expect(screen.queryByTestId("catalog-card")).not.toBeInTheDocument();
    expect(
      screen.getByText('Search:empty:{"query":"no-results"}'),
    ).toBeInTheDocument();
  });

  it("renders the results grid and forwards pagination with the active filters", async () => {
    searchCatalog.mockResolvedValue({
      status: "ok",
      results: [resultItem],
      total: 41,
      page: 1,
      limit: 24,
    });

    render(
      await renderPage({
        q: "dune",
        date_from: "2020-01-01",
        rating_external_min: "6.5",
      }),
    );

    const cards = screen.getAllByTestId("catalog-card");
    expect(cards).toHaveLength(1);
    expect(JSON.parse(cards[0].getAttribute("data-props")!)).toMatchObject({
      title: "Dune",
      href: "/movie/dune-2021",
    });

    const pagination = screen.getByTestId("search-pagination");
    const paginationProps = JSON.parse(pagination.getAttribute("data-props")!);
    expect(paginationProps).toMatchObject({
      query: "dune",
      page: 1,
      totalPages: 2,
      dateFrom: "2020-01-01",
      ratingExternalMin: 6.5,
    });
  });
});
