import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

import {
  DEFAULT_CATALOG_SORT,
  type CatalogGenre,
  type CatalogListItem,
  type CatalogListResult,
  type CatalogSort,
  type CatalogType,
} from "./catalog-types";

/**
 * Public (no-auth, no-cookies) fetch helpers for the catalog's public pages:
 * the home page's trending (TMDB-backed) and "featured" per-type sections
 * (FE-8), and the `/browse/{type}` paginated, filterable list (FE-9). Local
 * catalog only, no external fallback for any of it.
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
 * spirit as `getCurrentUser()` in `src/lib/api-fetch.ts`. The one exception
 * is {@link listCatalog}, whose result IS the page (`/browse/{type}`) — see
 * its own doc comment for why it reports failure explicitly instead.
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
