import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

import { isCatalogType, type CatalogType } from "./catalog-types";

/**
 * Server-side (no-auth, no-cookies) data source for the global search page
 * (FE-11), `GET /v1/search`. Same split rationale as `./catalog.ts`: this
 * file transitively pulls in `server-only` through `@/lib/auth/session`, so
 * `./catalog-types.ts` stays the framework-agnostic import for Client
 * Components (e.g. `src/components/search-controls.tsx`).
 */

export type SearchResultItem = components["schemas"]["SearchResultItem"];

export type SearchOptions = {
  type?: CatalogType;
  page?: number;
};

/**
 * Result of {@link searchCatalog}. Distinct `status` values (rather than a
 * single `ok`/`error` split like `listCatalog`) because the search page must
 * tell apart four cases with genuinely different UX (FE-11 acceptance):
 * a normal result set (possibly empty — `results: []` is a real "no matches"
 * state, not an error), a defensive 422 (the client never submits an empty
 * `q`, but the backend validates it too), and a 429 from the external
 * fallback's per-IP rate limit, which carries the `Retry-After` header value
 * so the page can surface a countdown instead of a generic error.
 */
export type SearchResult =
  | { status: "ok"; results: SearchResultItem[]; total: number; page: number; limit: number }
  | { status: "invalid" }
  | { status: "rate-limited"; retryAfterSeconds: number | null }
  | { status: "error" };

/** Page size for the search results grid — matches `BROWSE_PAGE_SIZE` (`./catalog.ts`) for a consistent grid layout. */
export const SEARCH_PAGE_SIZE = 24;

/**
 * Cross-type search, `GET /v1/search?q=&type=&page=&limit=`. Deliberately
 * uncached (no `next.revalidate`): unlike the catalog list/browse endpoints
 * (which only change via the nightly sync), a search query can itself
 * trigger the backend's on-demand external fallback and ingest new items —
 * caching a query's first (possibly empty-fallback-triggering) response
 * would be wrong.
 */
export async function searchCatalog(
  query: string,
  options: SearchOptions = {},
): Promise<SearchResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/search", {
      params: {
        query: {
          q: query,
          type: options.type,
          page: options.page ?? 1,
          limit: SEARCH_PAGE_SIZE,
        },
      },
    });

    if (response.status === 200 && data) {
      return { status: "ok", ...data };
    }
    if (response.status === 422) {
      return { status: "invalid" };
    }
    if (response.status === 429) {
      return { status: "rate-limited", retryAfterSeconds: parseRetryAfter(response) };
    }
    return { status: "error" };
  } catch (error) {
    console.error(`searchCatalog(${query}): failed to reach the API`, error);
    return { status: "error" };
  }
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (!header) {
    return null;
  }
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/**
 * Maps the backend's uppercase `item_type` (e.g. `"MOVIE"`, per
 * `docs/api.md`'s `/v1/search` example) to the route-segment `CatalogType`
 * used to link to `/{type}/{slug}` (FE-10). Returns `undefined` for any
 * unrecognized value so callers can render the result without a link rather
 * than throw.
 */
export function toCatalogType(itemType: string): CatalogType | undefined {
  const lower = itemType.toLowerCase();
  return isCatalogType(lower) ? lower : undefined;
}
