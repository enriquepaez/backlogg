/**
 * Framework-agnostic catalog vocabulary: route-segment types, sort orders,
 * and the plain data shapes shared across list/browse responses. No
 * `server-only` import (directly or transitively) — safe to import from
 * Client Components (e.g. `src/components/browse-filters.tsx`, a "use
 * client" component that needs `CATALOG_SORTS`/`DEFAULT_CATALOG_SORT` at
 * runtime) as well as Server Components.
 *
 * `./catalog.ts` holds the actual data-fetching functions and re-exports
 * everything here for convenience — but it also imports `getApiClient()`
 * from `@/lib/auth/session`, which starts with `import "server-only"`.
 * Importing `./catalog.ts` from a Client Component bundle would fail at
 * `next build` through that transitive import even for symbols (like these)
 * that don't themselves touch the network — hence this split.
 */

/**
 * Route-segment vocabulary for `/browse/{type}` (FE-9) and for picking which
 * "featured" list to fetch (FE-8). Mirrors the backend's singular lowercase
 * type names.
 */
export type CatalogType = "movie" | "series" | "book" | "game";

export const CATALOG_TYPES: readonly CatalogType[] = [
  "movie",
  "series",
  "book",
  "game",
];

function isCatalogTypeCandidate(value: string): value is CatalogType {
  return (CATALOG_TYPES as readonly string[]).includes(value);
}

/** Type guard for a raw route param (e.g. `/browse/[type]`) against {@link CatalogType}. */
export function isCatalogType(value: string): value is CatalogType {
  return isCatalogTypeCandidate(value);
}

/**
 * Shape shared by `MovieListItemOut` / `SeriesListItemOut` / `BookListItemOut`
 * / `GameListItemOut` — all four `/v1/{type}s` list endpoints return
 * identical fields, so callers can render any of them with one component.
 */
export type CatalogListItem = {
  id: number;
  title: string;
  slug: string;
  poster_url: string | null;
  release_date: string | null;
  rating_external: number | null;
  genres: string[];
};

/**
 * Sort order for the `/v1/{type}` list endpoints (FE-9 browse). Identical
 * literal union across all four types (`MovieSortEnum` / `SeriesSortEnum` /
 * `BookSortEnum` / `GameSortEnum` in the generated schema all share the same
 * values), so one shared type covers every endpoint.
 */
export type CatalogSort =
  | "rating_desc"
  | "rating_asc"
  | "date_desc"
  | "date_asc"
  | "title_asc";

export const CATALOG_SORTS: readonly CatalogSort[] = [
  "rating_desc",
  "rating_asc",
  "date_desc",
  "date_asc",
  "title_asc",
];

export const DEFAULT_CATALOG_SORT: CatalogSort = "rating_desc";

/** A genre option for the browse filter UI, from `GET /v1/genres?type=`. */
export type CatalogGenre = {
  name: string;
  slug: string;
  count: number;
};

export type CatalogListPage = {
  items: CatalogListItem[];
  total: number;
  page: number;
  limit: number;
};

/**
 * A genre annotated with its content type — the shape `GET /v1/genres`
 * actually returns (`GenreWithCountOut.item_type`), used by the `/genres`
 * browse page (FE-12) to group genres per type and to build the link to
 * `/browse/{item_type}?genre=slug`. Unlike {@link CatalogGenre} (the
 * per-type filter dropdown option on `/browse/{type}`, FE-9), `item_type` is
 * redundant there — the caller already knows which type it asked for — so
 * that shape omits it.
 */
export type GenreWithType = CatalogGenre & { item_type: CatalogType };

/**
 * Trending only covers movies and series (TMDB Trending API — see
 * `docs/api.md`'s `/v1/trending`), unlike {@link CatalogType}, which also
 * includes books and games for the rest of the catalog.
 */
export type TrendingType = "movie" | "series";

export const TRENDING_TYPES: readonly TrendingType[] = ["movie", "series"];

/** Sort of `/v1/trending`'s `period` query param (`docs/api.md`). */
export type TrendingPeriod = "day" | "week";

export const TRENDING_PERIODS: readonly TrendingPeriod[] = ["day", "week"];

export const DEFAULT_TRENDING_PERIOD: TrendingPeriod = "week";

/**
 * Result of `listCatalog` (see `./catalog.ts`). Unlike `getFeatured` (which
 * silently degrades to an empty array — a failed home page section is a
 * minor, non-blocking gap) the browse page's grid is the whole point of the
 * route, so callers need to tell "the API returned zero results" (`ok: true`,
 * `items: []` — a real empty state) apart from "the API call itself failed"
 * (`ok: false` — an error state) to satisfy FE-9's empty/error UI
 * requirement.
 */
export type CatalogListResult = ({ ok: true } & CatalogListPage) | { ok: false };
