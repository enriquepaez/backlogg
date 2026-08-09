import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

/**
 * Public (no-auth, no-cookies) fetch helpers for the home page's catalog
 * sections: trending (TMDB-backed) and "featured" per-type listings (local
 * catalog only, no external fallback).
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
 * Every export here degrades to an empty array on failure (network error or
 * non-200 response) instead of throwing: this is a public SEO page where one
 * failing section must not take down the rest of the render — same spirit as
 * `getCurrentUser()` in `src/lib/api-fetch.ts`.
 */

export type TrendingItem = components["schemas"]["TrendingItemOut"];

/**
 * Route-segment vocabulary for `/browse/{type}` (FE-9, not built yet) and
 * for picking which "featured" list to fetch. Mirrors the backend's
 * singular lowercase type names.
 */
export type CatalogType = "movie" | "series" | "book" | "game";

export const CATALOG_TYPES: readonly CatalogType[] = [
  "movie",
  "series",
  "book",
  "game",
];

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
