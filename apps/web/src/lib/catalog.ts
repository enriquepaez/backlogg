import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

import {
  DEFAULT_CATALOG_SORT,
  type CatalogGenre,
  type CatalogListItem,
  type CatalogListResult,
  type CatalogSort,
  type CatalogType,
  type GenreWithType,
  type TrendingPeriod,
  type TrendingType,
} from "./catalog-types";

/**
 * Public (no-auth, no-cookies) fetch helpers for the catalog's public pages:
 * the home page's trending (TMDB-backed) and "featured" per-type sections
 * (FE-8), the `/browse/{type}` paginated, filterable list (FE-9), and the
 * `/{type}/{slug}` item detail page + its "similar" section (FE-10). Local
 * catalog only, no external fallback for any of it — except the item detail
 * fetch itself, which hits the backend's own on-demand fallback (see
 * {@link getItemDetail}'s doc comment).
 *
 * Reuses the shared `getApiClient()` from `@/lib/auth/session` — that module
 * already starts with `import "server-only"`, which guards this file
 * transitively (bundling it into a Client Component would still fail at
 * build time through that import), so this file doesn't need its own
 * `"server-only"` marker. Skipping it here is deliberate: it keeps this
 * module importable by a plain Vitest unit test (mocking only
 * `@/lib/auth/session`) instead of requiring a Next.js bundler to resolve
 * the `server-only` package — see `src/lib/catalog.test.ts`.
 *
 * The pure vocabulary (route-segment types, sort orders, list item shapes)
 * lives in `./catalog-types.ts` and is re-exported below — that module has
 * no `server-only` dependency, so Client Components that only need the
 * vocabulary (e.g. `src/components/browse-filters.tsx`) import it directly
 * instead of through here.
 *
 * Most exports here degrade to an empty array on failure (network error or
 * non-200 response) instead of throwing: this is public SEO content where
 * one failing section must not take down the rest of the render — same
 * spirit as `getCurrentUser()` in `src/lib/api-fetch.ts`. The exceptions are
 * {@link listCatalog} and {@link getItemDetail}, whose result IS the page
 * (`/browse/{type}` and `/{type}/{slug}` respectively) — see their own doc
 * comments for why they report failure explicitly instead.
 */

export * from "./catalog-types";

export type TrendingItem = components["schemas"]["TrendingItemOut"];

/**
 * ISR window for the trending section (fetch-level `next.revalidate`, see
 * `src/app/[locale]/page.tsx` for why a page-level `export const revalidate`
 * would not produce real ISR here). TMDB trending shifts through the day,
 * and an uncached hit both calls TMDB and writes newly-seen items to the
 * local DB (`backlogg/trending/service.py`) — not free to hit on every
 * request either.
 */
const TRENDING_REVALIDATE_SECONDS = 60 * 60; // 1h

/**
 * ISR window for the "featured" per-type sections. These read the local
 * catalog only (no external fallback), which changes at most once a day via
 * the nightly sync (GitHub Actions) — safe to cache much longer than
 * trending.
 */
const FEATURED_REVALIDATE_SECONDS = 60 * 60 * 6; // 6h

const FEATURED_LIMIT = 8;

/**
 * ISR window for the `/browse/{type}` list + genre filter (FE-9). Same
 * cadence as {@link FEATURED_REVALIDATE_SECONDS} — both read the local
 * catalog only, which only changes via the nightly sync.
 */
const BROWSE_REVALIDATE_SECONDS = FEATURED_REVALIDATE_SECONDS;

/** Page size for the `/browse/{type}` grid. Not user-configurable (no `limit` picker in the UI). */
export const BROWSE_PAGE_SIZE = 24;

/** Trending movies + series (this week), TMDB-backed. */
export async function getTrending(): Promise<TrendingItem[]> {
  try {
    const { data, response } = await getApiClient().GET("/v1/trending", {
      next: { revalidate: TRENDING_REVALIDATE_SECONDS },
    });
    return response.status === 200 && data ? data.results : [];
  } catch (error) {
    console.error("getTrending: failed to reach the API", error);
    return [];
  }
}

/** Top-rated items (by `rating_desc`) for one catalog type, for the home page's "featured" rows. */
export async function getFeatured(type: CatalogType): Promise<CatalogListItem[]> {
  try {
    const client = getApiClient();
    const next = { revalidate: FEATURED_REVALIDATE_SECONDS };

    switch (type) {
      case "movie": {
        const { data, response } = await client.GET("/v1/movies", {
          params: { query: { sort: "rating_desc", limit: FEATURED_LIMIT } },
          next,
        });
        return response.status === 200 && data ? data.items : [];
      }
      case "series": {
        const { data, response } = await client.GET("/v1/series", {
          params: { query: { sort: "rating_desc", limit: FEATURED_LIMIT } },
          next,
        });
        return response.status === 200 && data ? data.items : [];
      }
      case "book": {
        const { data, response } = await client.GET("/v1/books", {
          params: { query: { sort: "rating_desc", limit: FEATURED_LIMIT } },
          next,
        });
        return response.status === 200 && data ? data.items : [];
      }
      case "game": {
        const { data, response } = await client.GET("/v1/games", {
          params: { query: { sort: "rating_desc", limit: FEATURED_LIMIT } },
          next,
        });
        return response.status === 200 && data ? data.items : [];
      }
    }
  } catch (error) {
    console.error(`getFeatured(${type}): failed to reach the API`, error);
    return [];
  }
}

export type ListCatalogOptions = {
  genre?: string;
  sort?: CatalogSort;
  page?: number;
};

/**
 * Paginated, filterable, sortable list for one catalog type — the data
 * source for `/browse/{type}` (FE-9). Unlike {@link getFeatured}, failures
 * are reported via {@link CatalogListResult} (`ok: false`) instead of
 * silently degrading to an empty page, so the browse page can render a
 * distinct error state (see that type's doc comment).
 */
export async function listCatalog(
  type: CatalogType,
  options: ListCatalogOptions = {},
): Promise<CatalogListResult> {
  const query = {
    genre: options.genre,
    sort: options.sort ?? DEFAULT_CATALOG_SORT,
    page: options.page ?? 1,
    limit: BROWSE_PAGE_SIZE,
  };
  const next = { revalidate: BROWSE_REVALIDATE_SECONDS };

  try {
    const client = getApiClient();

    switch (type) {
      case "movie": {
        const { data, response } = await client.GET("/v1/movies", {
          params: { query },
          next,
        });
        return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
      }
      case "series": {
        const { data, response } = await client.GET("/v1/series", {
          params: { query },
          next,
        });
        return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
      }
      case "book": {
        const { data, response } = await client.GET("/v1/books", {
          params: { query },
          next,
        });
        return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
      }
      case "game": {
        const { data, response } = await client.GET("/v1/games", {
          params: { query },
          next,
        });
        return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
      }
    }
  } catch (error) {
    console.error(`listCatalog(${type}): failed to reach the API`, error);
    return { ok: false };
  }
}

/**
 * Genre options for the `/browse/{type}` filter dropdown (FE-9),
 * `GET /v1/genres?type=`. Degrades to an empty array on failure — a missing
 * filter list is not fatal, unlike a failed {@link listCatalog} call: the
 * grid itself still renders (unfiltered), just without a genre picker.
 */
export async function getGenres(type: CatalogType): Promise<CatalogGenre[]> {
  try {
    const { data, response } = await getApiClient().GET("/v1/genres", {
      params: { query: { type } },
      next: { revalidate: BROWSE_REVALIDATE_SECONDS },
    });
    return response.status === 200 && data
      ? data.genres.map((genre) => ({
          name: genre.name,
          slug: genre.slug,
          count: genre.count,
        }))
      : [];
  } catch (error) {
    console.error(`getGenres(${type}): failed to reach the API`, error);
    return [];
  }
}

export type GenrePageResult = { ok: true; genres: GenreWithType[] } | { ok: false };

/**
 * All genres (optionally filtered by content type), for the `/genres` browse
 * page (FE-12). Unlike {@link getGenres} — the `/browse/{type}` filter
 * dropdown's data source, which silently degrades to an empty array because a
 * missing filter list there isn't fatal — this page's whole point IS the
 * genre list, so failures are reported explicitly via `ok: false`, same
 * reasoning as {@link listCatalog}. Also keeps `item_type` (dropped by
 * {@link getGenres}, redundant there since the caller already knows the
 * type it asked for) since this page groups genres by type and links each
 * one to `/browse/{item_type}?genre=slug`.
 */
export async function getGenrePage(type?: CatalogType): Promise<GenrePageResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/genres", {
      params: { query: { type } },
      next: { revalidate: BROWSE_REVALIDATE_SECONDS },
    });
    if (response.status !== 200 || !data) {
      return { ok: false };
    }
    return {
      ok: true,
      genres: data.genres.map((genre) => ({
        name: genre.name,
        slug: genre.slug,
        count: genre.count,
        item_type: genre.item_type as CatalogType,
      })),
    };
  } catch (error) {
    console.error(`getGenrePage(${type}): failed to reach the API`, error);
    return { ok: false };
  }
}

export type TrendingPageOptions = { type?: TrendingType; period?: TrendingPeriod };

export type TrendingPageResult = { ok: true; results: TrendingItem[] } | { ok: false };

/**
 * Trending items filtered by type/period, for the `/trending` browse page
 * (FE-12). Same explicit `ok`-tagged pattern as {@link getGenrePage}/
 * {@link listCatalog} — unlike {@link getTrending} (the home page's trending
 * section, which silently degrades to an empty array since a failed home
 * section is a minor, non-blocking gap), this page's whole point IS the
 * trending list.
 */
export async function getTrendingPage(
  options: TrendingPageOptions = {},
): Promise<TrendingPageResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/trending", {
      params: { query: { type: options.type, period: options.period } },
      next: { revalidate: TRENDING_REVALIDATE_SECONDS },
    });
    if (response.status !== 200 || !data) {
      return { ok: false };
    }
    return { ok: true, results: data.results };
  } catch (error) {
    console.error("getTrendingPage: failed to reach the API", error);
    return { ok: false };
  }
}

/**
 * Maps the trending endpoint's uppercase `item_type` (`TrendingItemOut`) to
 * the lowercase {@link TrendingType} vocabulary used elsewhere (routes,
 * `Home.typeBadge`). Shared by the home page's trending section (FE-8) and
 * the `/trending` browse page (FE-12).
 */
export function trendingItemType(item: TrendingItem): TrendingType {
  return item.item_type === "MOVIE" ? "movie" : "series";
}

/** All four "featured" lists, fetched in parallel, keyed by {@link CatalogType}. */
export async function getAllFeatured(): Promise<
  Record<CatalogType, CatalogListItem[]>
> {
  const [movie, series, book, game] = await Promise.all([
    getFeatured("movie"),
    getFeatured("series"),
    getFeatured("book"),
    getFeatured("game"),
  ]);
  return { movie, series, book, game };
}

export type MovieDetail = components["schemas"]["MovieOut"];
export type SeriesDetail = components["schemas"]["SeriesOut"];
export type BookDetail = components["schemas"]["BookOut"];
export type GameDetail = components["schemas"]["GameOut"];

/**
 * `GET /v1/{type}/{slug}` response shape, keyed by {@link CatalogType}. Unlike
 * {@link CatalogListItem} (identical fields across all four list endpoints),
 * the four detail shapes genuinely differ (e.g. `runtime` vs
 * `number_of_seasons` vs `first_publish_date` vs `platforms`) — callers of
 * {@link getItemDetail} narrow `ItemDetail` back down using the same `type`
 * value the result came from (see `[locale]/[type]/[slug]/page.tsx`).
 */
export type ItemDetail = MovieDetail | SeriesDetail | BookDetail | GameDetail;

/**
 * Result of {@link getItemDetail} (FE-10 item detail page). Three states,
 * not just success/failure, because the page needs to tell apart a
 * backend-confirmed "this slug doesn't exist anywhere" (`docs/api.md`: 404
 * means "Not found in DB or external API" — the on-demand fallback already
 * ran and found nothing) from merely failing to reach the API at all
 * (network error, timeout, unexpected 5xx). Only the former is safe to
 * surface via `notFound()`. A transient failure must not be treated as a
 * permanent 404: the backend's on-demand fallback (`docs/architecture.md`)
 * can itself take a while the first time a slug is requested — it still
 * completes within that same request and returns 200, but if the fetch from
 * *this* app fails for any reason (e.g. a slow external-API round trip on
 * the backend outlasting some intermediary timeout), the right response is
 * an inline, retryable error state, not a hard "page not found" that would
 * get treated as permanent by a search engine or a returning user. A reload
 * simply calls {@link getItemDetail} again — by then the item is already
 * persisted locally, so the retry is fast and returns `"ok"`. See FE-10's
 * acceptance criteria in `frontend_feature_list.json`.
 */
export type ItemDetailResult<T> =
  | { status: "ok"; item: T }
  | { status: "not-found" }
  | { status: "error" };

/**
 * ISR window for a single item's detail fetch. Shorter than
 * {@link FEATURED_REVALIDATE_SECONDS}/{@link BROWSE_REVALIDATE_SECONDS}: this
 * is the endpoint the on-demand fallback most directly targets (a slug
 * requested here for the first time gets persisted synchronously and
 * returned in the same response), so a freshly-created item's own page
 * should reflect that soon rather than wait up to 6h.
 */
const ITEM_REVALIDATE_SECONDS = 60 * 60; // 1h

/**
 * Cache tag for a single item's {@link getItemDetail} fetch (bugfix: the
 * item detail page's "Backlogg rating" — both `ItemHero`'s static chip and
 * `RatingWidget`'s own `initialRatingInternal`/`initialRatingCountInternal`
 * seed — otherwise stayed stuck at whatever `rating_internal`/
 * `rating_count_internal` this fetch first cached for up to
 * {@link ITEM_REVALIDATE_SECONDS}, even right after the viewer's own rating
 * changed those aggregates server-side: reproduced live against the real
 * backend — `GET /v1/{type}/{slug}` already returned the fresh
 * `rating_internal` on the wire, but a full reload of the item detail page
 * kept rendering "No ratings yet" until the ISR window rolled over).
 *
 * `PUT`/`DELETE /api/{type}/{slug}/rating` (`route.ts`) call
 * `revalidateTag(itemDetailCacheTag(type, slug), { expire: 0 })` (immediate
 * expiration — see that route's doc comment for why Next 16's recommended
 * `"max"` profile isn't good enough here) after a successful backend
 * mutation so the next request for this item's detail page re-fetches
 * instead of serving the stale cached aggregate — locale-independent (same
 * as the fetch itself, `getItemDetail` never varies by locale), so one tag
 * covers both `/en/{type}/{slug}` and `/es/{type}/{slug}`.
 */
export function itemDetailCacheTag(type: CatalogType, slug: string): string {
  return `item-detail:${type}:${slug}`;
}

/**
 * Fetch one item's full detail by type + slug (FE-10). Only ever reports a
 * `"not-found"` result for a real backend 404 — any other failure (network
 * error, non-200/404 status) reports `"error"` instead. See
 * {@link ItemDetailResult} for why that distinction matters.
 */
export async function getItemDetail(
  type: CatalogType,
  slug: string,
): Promise<ItemDetailResult<ItemDetail>> {
  const next = { revalidate: ITEM_REVALIDATE_SECONDS, tags: [itemDetailCacheTag(type, slug)] };

  try {
    const client = getApiClient();

    switch (type) {
      case "movie": {
        const { data, response } = await client.GET("/v1/movies/{slug}", {
          params: { path: { slug } },
          next,
        });
        if (response.status === 200 && data) return { status: "ok", item: data };
        return response.status === 404 ? { status: "not-found" } : { status: "error" };
      }
      case "series": {
        const { data, response } = await client.GET("/v1/series/{slug}", {
          params: { path: { slug } },
          next,
        });
        if (response.status === 200 && data) return { status: "ok", item: data };
        return response.status === 404 ? { status: "not-found" } : { status: "error" };
      }
      case "book": {
        const { data, response } = await client.GET("/v1/books/{slug}", {
          params: { path: { slug } },
          next,
        });
        if (response.status === 200 && data) return { status: "ok", item: data };
        return response.status === 404 ? { status: "not-found" } : { status: "error" };
      }
      case "game": {
        const { data, response } = await client.GET("/v1/games/{slug}", {
          params: { path: { slug } },
          next,
        });
        if (response.status === 200 && data) return { status: "ok", item: data };
        return response.status === 404 ? { status: "not-found" } : { status: "error" };
      }
    }
  } catch (error) {
    console.error(`getItemDetail(${type}, ${slug}): failed to reach the API`, error);
    return { status: "error" };
  }
}

/** A `similar` result item — identical shape for movies (`SimilarMovieOut`) and series (`SimilarSeriesOut`). */
export type SimilarItem = components["schemas"]["SimilarMovieOut"];

/**
 * "Similar" items for the item detail page's similar section (FE-10) — only
 * defined for movies and series (`GET /v1/{movies,series}/{slug}/similar`,
 * TMDB recommendations, `docs/api.md`). Books and games have no equivalent
 * endpoint, so this degrades to an empty array for those types without
 * attempting a request. Also degrades to an empty array on any failure
 * (network error or non-200 response) — same spirit as
 * {@link getTrending}/{@link getFeatured}: this is a secondary section, not
 * the point of the page (unlike {@link getItemDetail}, whose failure IS the
 * page).
 */
export async function getSimilarItems(
  type: CatalogType,
  slug: string,
): Promise<SimilarItem[]> {
  if (type !== "movie" && type !== "series") {
    return [];
  }

  try {
    const client = getApiClient();
    const next = { revalidate: ITEM_REVALIDATE_SECONDS };

    if (type === "movie") {
      const { data, response } = await client.GET("/v1/movies/{slug}/similar", {
        params: { path: { slug } },
        next,
      });
      return response.status === 200 && data ? data.results : [];
    }

    const { data, response } = await client.GET("/v1/series/{slug}/similar", {
      params: { path: { slug } },
      next,
    });
    return response.status === 200 && data ? data.results : [];
  } catch (error) {
    console.error(`getSimilarItems(${type}, ${slug}): failed to reach the API`, error);
    return [];
  }
}
