import type { ApiClient, components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

import type { CatalogType } from "./catalog-types";
import {
  DEFAULT_LIBRARY_SORT,
  DEFAULT_LIBRARY_VIEW,
  isLibrarySort,
  isLibraryStatus,
  isLibraryView,
  LIBRARY_SORTS,
  LIBRARY_STATUSES,
  LIBRARY_VIEWS,
  reviewScoreKey,
  sortLibraryEntries,
  STATUS_COLOR_CLASSES,
  type LibraryEntry,
  type LibrarySort,
  type LibraryStatusValue,
  type LibraryView,
} from "./library-types";

/**
 * Library/backlog helpers (FE-20): add/change/remove the caller's own
 * per-item status, and read a user's public library. Two distinct call
 * shapes in this one file, matching the two distinct contexts that need
 * them:
 *
 * - `putLibraryStatus`/`deleteLibraryStatus`/`getViewerLibraryStatus` take
 *   `client`/`headers` explicitly (same dispatch shape as `./ratings.ts`'s
 *   `putRating`/`deleteRating`) — these back the auth-required BFF route
 *   (`src/app/api/[type]/[slug]/library/route.ts`), which needs `apiFetch`'s
 *   token-refresh dance around the actual call.
 * - `getUserLibrary`/`getUserProfile` are self-contained (own
 *   `getApiClient()`, own try/catch, own status interpretation) because both
 *   backing endpoints are public — no BFF proxy needed, no token to attach —
 *   same house style as `./catalog.ts`'s `listCatalog`/`getGenrePage` and
 *   `./search.ts`'s `searchCatalog`. The `/u/{username}/library` page
 *   (`src/app/[locale]/u/[username]/library/page.tsx`) calls these directly.
 *
 * There is no dedicated "my library status" endpoint (same gap as ratings,
 * see `./ratings.ts`'s doc comment) — `getViewerLibraryStatus` reuses
 * `GET /v1/{type}/{slug}` with the caller's bearer token attached and reads
 * back `viewer_status`, which every item detail response already echoes for
 * an authenticated caller (`docs/api.md`). Unlike the ratings workaround,
 * this needs no pagination/scanning: `viewer_status` is a single field
 * directly on the detail response.
 */

export type { LibraryEntry, LibrarySort, LibraryStatusValue, LibraryView };
export {
  DEFAULT_LIBRARY_SORT,
  DEFAULT_LIBRARY_VIEW,
  isLibrarySort,
  isLibraryStatus,
  isLibraryView,
  LIBRARY_SORTS,
  LIBRARY_STATUSES,
  LIBRARY_VIEWS,
  sortLibraryEntries,
  STATUS_COLOR_CLASSES,
};

export type LibraryStatusOut = components["schemas"]["LibraryStatusOut"];
export type UserProfile = components["schemas"]["UserOut"];

type ApiResult<T> = { data?: T; response: Response };

/** `PUT /v1/{type}/{slug}/library` — upsert the caller's backlog status (`docs/api.md`). */
export async function putLibraryStatus(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
  status: LibraryStatusValue,
): Promise<ApiResult<LibraryStatusOut>> {
  const body = { status };
  switch (type) {
    case "movie":
      return client.PUT("/v1/movies/{slug}/library", { params: { path: { slug } }, body, headers });
    case "series":
      return client.PUT("/v1/series/{slug}/library", { params: { path: { slug } }, body, headers });
    case "book":
      return client.PUT("/v1/books/{slug}/library", { params: { path: { slug } }, body, headers });
    case "game":
      return client.PUT("/v1/games/{slug}/library", { params: { path: { slug } }, body, headers });
  }
}

/** `DELETE /v1/{type}/{slug}/library` — remove the caller's own library entry (`docs/api.md`). */
export async function deleteLibraryStatus(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
): Promise<ApiResult<undefined>> {
  switch (type) {
    case "movie":
      return client.DELETE("/v1/movies/{slug}/library", { params: { path: { slug } }, headers });
    case "series":
      return client.DELETE("/v1/series/{slug}/library", { params: { path: { slug } }, headers });
    case "book":
      return client.DELETE("/v1/books/{slug}/library", { params: { path: { slug } }, headers });
    case "game":
      return client.DELETE("/v1/games/{slug}/library", { params: { path: { slug } }, headers });
  }
}

/** The subset of `MovieOut`/`SeriesOut`/`BookOut`/`GameOut` that {@link getViewerLibraryStatus} actually needs. */
type ItemDetailViewerStatus = { viewer_status?: string | null };

/**
 * `GET /v1/{type}/{slug}` with the caller's bearer token attached, read back
 * for its `viewer_status` field only — see this module's doc comment for why
 * there is no more direct endpoint. Used by
 * `GET /api/{type}/{slug}/library` (the BFF route backing `ViewerStatusSlot`).
 */
export async function getViewerLibraryStatus(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
): Promise<ApiResult<ItemDetailViewerStatus>> {
  switch (type) {
    case "movie":
      return client.GET("/v1/movies/{slug}", { params: { path: { slug } }, headers });
    case "series":
      return client.GET("/v1/series/{slug}", { params: { path: { slug } }, headers });
    case "book":
      return client.GET("/v1/books/{slug}", { params: { path: { slug } }, headers });
    case "game":
      return client.GET("/v1/games/{slug}", { params: { path: { slug } }, headers });
  }
}

export type LibraryQuery = {
  status?: LibraryStatusValue;
  type?: CatalogType;
  page?: number;
  limit?: number;
};

export type LibraryPageResult =
  | { ok: true; items: LibraryEntry[]; total: number; page: number; limit: number }
  | { ok: false };

/**
 * `GET /v1/users/{username}/library?status=&type=&page=&limit=` — public,
 * paginated, cross-type (`docs/api.md`). Same `ok`-tagged result shape as
 * `./catalog.ts`'s `listCatalog`: this is the whole point of the
 * `/u/{username}/library` page, so a failure is reported explicitly rather
 * than silently degrading to an empty page.
 */
export async function getUserLibrary(
  username: string,
  query: LibraryQuery = {},
): Promise<LibraryPageResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/library", {
      params: { path: { username }, query },
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getUserLibrary(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}

/**
 * `GET /v1/users/{username}/reviews?limit=` scanned for a per-item score
 * map (FE-38's `rating_desc` library sort), keyed by
 * {@link reviewScoreKey}. There is no `sort` param on
 * `GET /v1/users/{username}/library` at all (`docs/api.md`) and its
 * `LibraryEntryOut` carries no rating field, only `rating_external`
 * (`LibraryItemOut`, the external critic/audience score — not what "your
 * rating" means here) — so `page.tsx` reads the library owner's own score
 * per item from this separate, already-public endpoint instead
 * (`GET /v1/users/{username}/reviews`, same one `/u/{username}` uses to
 * list reviews) and merges it in client-side via `sortLibraryEntries`.
 *
 * `REVIEW_SCORE_SCAN_LIMIT` mirrors `MY_RATING_SCAN_LIMIT`
 * (`src/app/api/[type]/[slug]/rating/route.ts`) — same backend cap
 * (`limit<=100`, `docs/api.md`) and the same accepted limitation: on a
 * library owner with more than 100 reviews, a rating outside the first 100
 * (newest first) is simply treated as unrated by `sortLibraryEntries`
 * (sorts last), rather than fetching every page. Only called when
 * `sort === "rating_desc"` (see `page.tsx`) — every other sort needs no
 * extra request.
 */
const REVIEW_SCORE_SCAN_LIMIT = 100;

export async function getUserReviewScores(username: string): Promise<Map<string, number>> {
  const scores = new Map<string, number>();
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/reviews", {
      params: { path: { username }, query: { limit: REVIEW_SCORE_SCAN_LIMIT } },
    });
    if (response.status !== 200 || !data) {
      return scores;
    }
    for (const review of data.items) {
      if (review.score !== null) {
        scores.set(reviewScoreKey(review.item.item_type, review.item.slug), review.score);
      }
    }
    return scores;
  } catch (error) {
    console.error(`getUserReviewScores(${username}): failed to reach the API`, error);
    return scores;
  }
}

export type UserProfileResult =
  | { status: "ok"; profile: UserProfile }
  | { status: "not-found" }
  | { status: "error" };

/**
 * `GET /v1/users/{username}` — public profile, including `library_counts`
 * (`docs/api.md`). Same `not-found`/`error` split as `./catalog.ts`'s
 * `getItemDetail`: only a real backend 404 is safe to surface via
 * `notFound()`, any other failure gets an inline, retryable error state.
 */
export async function getUserProfile(username: string): Promise<UserProfileResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}", {
      params: { path: { username } },
    });
    if (response.status === 200 && data) return { status: "ok", profile: data };
    return response.status === 404 ? { status: "not-found" } : { status: "error" };
  } catch (error) {
    console.error(`getUserProfile(${username}): failed to reach the API`, error);
    return { status: "error" };
  }
}
