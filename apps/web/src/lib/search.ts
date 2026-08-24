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
  /**
   * Re-scope of FE-35 (`browse_search_filters`, Fase 1 backend): `GET /v1/search`
   * now also accepts a date-range and an external-rating-range filter,
   * independently optional and combinable with `q`/`type`. Mirrors
   * `ListCatalogOptions` (`./catalog.ts`) minus `ratingInternalMin`/`Max` —
   * `catalog_search` (the view backing this endpoint) has no
   * `rating_internal` column, so there is no internal-rating filter here.
   */
  dateFrom?: string;
  dateTo?: string;
  ratingExternalMin?: number;
  ratingExternalMax?: number;
};

/**
 * Result of {@link searchCatalog}. Distinct `status` values (rather than a
 * single `ok`/`error` split like `listCatalog`) because the search page must
 * tell apart four cases with genuinely different UX (FE-11 acceptance):
 * a normal result set (possibly empty — `results: []` is a real "no matches"
 * state, not an error), a 422 (the client never intentionally submits an
 * empty `q` or an invalid date/rating range — `SearchControls`, re-scope of
 * FE-35, validates both client-side — but the backend validates them too, so
 * this stays reachable defensively, e.g. a hand-edited/shared URL), and a 429
 * from the external fallback's per-IP rate limit, which carries the
 * `Retry-After` header value so the page can surface a countdown instead of
 * a generic error.
 */
export type SearchResult =
  | { status: "ok"; results: SearchResultItem[]; total: number; page: number; limit: number }
  | { status: "invalid" }
  | { status: "rate-limited"; retryAfterSeconds: number | null }
  | { status: "error" };

/**
 * Page size for the search results grid. Deliberately smaller than
 * `BROWSE_PAGE_SIZE` (`./catalog.ts`, 24) — a smaller page keeps each
 * external-fallback fan-out trip (issue #14, `backlogg/search/service.py`)
 * a cheap, incremental unit of catalog completion as the user pages
 * further, rather than one large batch. Still divides evenly into the
 * results grid's column counts (2/3/4/6, `search/page.tsx`).
 */
export const SEARCH_PAGE_SIZE = 12;

/**
 * Cross-type search, `GET /v1/search?q=&type=&page=&limit=&date_from=&date_to=&rating_external_min=&rating_external_max=`.
 * Deliberately uncached (no `next.revalidate`): unlike the catalog
 * list/browse endpoints (which only change via the nightly sync), a search
 * query can itself trigger the backend's on-demand external fallback and
 * ingest new items — caching a query's first (possibly
 * empty-fallback-triggering) response would be wrong.
 *
 * `query` may be `""` — the backend accepts `q` *absent* (a filters-only
 * search) but still 422s on `q=""` *explicit* (`Field(min_length=1)` when
 * present), same distinction `backlogg/search/schemas.py` draws. So an empty
 * (or whitespace-only) `query` omits the `q` param entirely rather than
 * sending it as an empty string.
 */
export async function searchCatalog(
  query: string,
  options: SearchOptions = {},
): Promise<SearchResult> {
  const trimmed = query.trim();

  try {
    const { data, response } = await getApiClient().GET("/v1/search", {
      params: {
        query: {
          q: trimmed || undefined,
          type: options.type,
          page: options.page ?? 1,
          limit: SEARCH_PAGE_SIZE,
          date_from: options.dateFrom,
          date_to: options.dateTo,
          rating_external_min: options.ratingExternalMin,
          rating_external_max: options.ratingExternalMax,
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
