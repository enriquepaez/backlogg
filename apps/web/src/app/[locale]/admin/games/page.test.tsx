import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same mocking approach as `admin/users/[username]/page.test.tsx` for
// `next-intl/server`: a namespace-agnostic echo is enough since this page's
// two namespaces (`Admin.catalog`, `Admin.sidebar`) never share a key name.
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}:${JSON.stringify(vars)}` : key,
  setRequestLocale: vi.fn(),
}));

const listCatalog = vi.fn();
const getGenres = vi.fn();
vi.mock("@/lib/catalog", () => ({
  listCatalog: (type: string, options: unknown) => listCatalog(type, options),
  getGenres: (type: string) => getGenres(type),
}));

// `AdminCatalogFilters`/`AdminCatalogTable`/`AdminCatalogPagination` are
// Client Components with their own dedicated tests — out of scope here, same
// rationale `admin/users/[username]/page.test.tsx` uses for mocking
// `AdminUserActionsPanel`. This page's own test only covers data-fetching
// and prop-wiring.
vi.mock("@/components/admin-catalog-filters", () => ({
  AdminCatalogFilters: (props: Record<string, unknown>) => (
    <div data-testid="admin-catalog-filters" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/admin-catalog-table", () => ({
  AdminCatalogTable: (props: Record<string, unknown>) => (
    <div data-testid="admin-catalog-table" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/admin-catalog-pagination", () => ({
  AdminCatalogPagination: (props: Record<string, unknown>) => (
    <div data-testid="admin-catalog-pagination" data-props={JSON.stringify(props)} />
  ),
}));

const { default: AdminGamesPage } = await import("./page");

const gameItem = {
  id: 1,
  title: "Hades",
  slug: "hades",
  poster_url: null,
  release_date: "2020-09-17",
  rating_external: 9.3,
  genres: ["roguelike"],
};

describe("AdminGamesPage", () => {
  it("renders the heading and description", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [gameItem], total: 1, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    render(await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByRole("heading", { name: "games" })).toBeInTheDocument();
    expect(screen.getByText('description:{"type":"games"}')).toBeInTheDocument();
  });

  it("parses genre/sort/page from searchParams and forwards them to listCatalog/getGenres", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [gameItem], total: 1, page: 2, limit: 24 });
    getGenres.mockResolvedValue([]);

    await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({ genre: "action", sort: "title_asc", page: "2" }),
    });

    expect(listCatalog).toHaveBeenCalledWith("game", { genre: "action", sort: "title_asc", page: 2 });
    expect(getGenres).toHaveBeenCalledWith("game");
  });

  it("falls back to defaults for missing/invalid searchParams", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [], total: 0, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({ page: "-3" }),
    });

    expect(listCatalog).toHaveBeenCalledWith("game", {
      genre: undefined,
      sort: "rating_desc",
      page: 1,
      search: undefined,
      dateFrom: undefined,
      dateTo: undefined,
      ratingInternalMin: undefined,
      ratingInternalMax: undefined,
      ratingExternalMin: undefined,
      ratingExternalMax: undefined,
    });
  });

  it("parses search/date/rating filters (feature 50) from searchParams and forwards them to listCatalog", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [gameItem], total: 1, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({
        search: "hades",
        date_from: "2018-01-01",
        date_to: "2021-12-31",
        rating_internal_min: "3",
        rating_internal_max: "5",
        rating_external_min: "8",
        rating_external_max: "10",
      }),
    });

    expect(listCatalog).toHaveBeenCalledWith("game", {
      genre: undefined,
      sort: "rating_desc",
      page: 1,
      search: "hades",
      dateFrom: "2018-01-01",
      dateTo: "2021-12-31",
      ratingInternalMin: 3,
      ratingInternalMax: 5,
      ratingExternalMin: 8,
      ratingExternalMax: 10,
    });
  });

  it("ignores malformed date/rating searchParams instead of forwarding garbage", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [], total: 0, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({ date_from: "not-a-date", rating_internal_min: "not-a-number" }),
    });

    expect(listCatalog).toHaveBeenCalledWith("game", {
      genre: undefined,
      sort: "rating_desc",
      page: 1,
      search: undefined,
      dateFrom: undefined,
      dateTo: undefined,
      ratingInternalMin: undefined,
      ratingInternalMax: undefined,
      ratingExternalMin: undefined,
      ratingExternalMax: undefined,
    });
  });

  it("forwards the parsed filters to AdminCatalogFilters and AdminCatalogPagination", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [gameItem], total: 41, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    render(
      await AdminGamesPage({
        params: Promise.resolve({ locale: "en" }),
        searchParams: Promise.resolve({ search: "hades", date_from: "2018-01-01", rating_external_min: "8" }),
      }),
    );

    const filters = screen.getByTestId("admin-catalog-filters");
    const filtersProps = JSON.parse(filters.getAttribute("data-props")!);
    expect(filtersProps).toMatchObject({
      selectedSearch: "hades",
      selectedDateFrom: "2018-01-01",
      selectedRatingExternalMin: 8,
    });

    const pagination = screen.getByTestId("admin-catalog-pagination");
    const paginationProps = JSON.parse(pagination.getAttribute("data-props")!);
    expect(paginationProps).toMatchObject({
      search: "hades",
      dateFrom: "2018-01-01",
      ratingExternalMin: 8,
    });
  });

  it("shows an error message when listCatalog fails", async () => {
    listCatalog.mockResolvedValue({ ok: false });
    getGenres.mockResolvedValue([]);

    render(await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByRole("alert")).toHaveTextContent("error");
    expect(screen.queryByTestId("admin-catalog-table")).not.toBeInTheDocument();
  });

  it("shows an empty message when there are no items", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [], total: 0, page: 1, limit: 24 });
    getGenres.mockResolvedValue([]);

    render(await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByText("empty")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-catalog-table")).not.toBeInTheDocument();
  });

  it("renders the results count, table and pagination with the right props when items are present", async () => {
    listCatalog.mockResolvedValue({ ok: true, items: [gameItem], total: 41, page: 1, limit: 24 });
    getGenres.mockResolvedValue([{ name: "Action", slug: "action", count: 5 }]);

    render(await AdminGamesPage({
      params: Promise.resolve({ locale: "en" }),
      searchParams: Promise.resolve({}),
    }));

    expect(screen.getByText('resultsCount:{"shown":1,"total":41}')).toBeInTheDocument();

    const table = screen.getByTestId("admin-catalog-table");
    const tableProps = JSON.parse(table.getAttribute("data-props")!);
    expect(tableProps.type).toBe("game");
    expect(tableProps.items).toEqual([gameItem]);
    expect(tableProps.dateLabel).toBe("dateLabel.game");

    const pagination = screen.getByTestId("admin-catalog-pagination");
    const paginationProps = JSON.parse(pagination.getAttribute("data-props")!);
    expect(paginationProps).toMatchObject({ type: "game", page: 1, totalPages: 2 });

    const filters = screen.getByTestId("admin-catalog-filters");
    const filtersProps = JSON.parse(filters.getAttribute("data-props")!);
    expect(filtersProps).toMatchObject({ type: "game", selectedSort: "rating_desc" });
    expect(filtersProps.genres).toEqual([{ name: "Action", slug: "action", count: 5 }]);
  });
});
