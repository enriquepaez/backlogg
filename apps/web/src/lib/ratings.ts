import type { ApiClient, components } from "@backlogg/api-client";

import type { CatalogType } from "./catalog-types";

/**
 * Server-side dispatch helpers for the ratings endpoints (FE-18/FE-19), used
 * only from Route Handlers (`src/app/api/[type]/[slug]/rating/route.ts`,
 * `src/app/api/[type]/[slug]/ratings/route.ts`, `src/app/api/reviews/[id]/like/route.ts`)
 * — never imported by a Client Component. Same reasoning/shape as
 * `./catalog.ts`'s per-type switches (`getItemDetail`, `getFeatured`, ...):
 * the generated client exposes one operation per literal path
 * (`/v1/movies/{slug}/rating`, `/v1/series/{slug}/rating`, ...), so there is
 * no single templated call to make across all four catalog types. The
 * like/unlike endpoints aren't per-type (`/v1/ratings/{rating_id}/like`
 * takes the review's own numeric id, not a `{type, slug}` pair), so
 * `likeReview`/`unlikeReview` below need no such switch.
 *
 * Each function returns the exact `{ data?, response }` shape `apiFetch`
 * (`src/lib/api-fetch.ts`) expects from the callback it wraps — `putRating`/
 * `deleteRating`/`likeReview`/`unlikeReview` are meant to be passed straight
 * through to `apiFetch` so an expired access token is transparently
 * refreshed once, same as every other authenticated BFF route. `listRatings`
 * is public (no auth token, mirrors `docs/api.md`: `GET /v1/{type}/{slug}/ratings`
 * requires no bearer token) so it takes a plain `ApiClient` instead.
 */

export type Rating = components["schemas"]["RatingOut"];
export type RatingPage = components["schemas"]["RatingListOut"];
export type RatingInput = { score: number | null; review_text: string | null };

type ApiResult<T> = { data?: T; response: Response };

/** `PUT /v1/{type}/{slug}/rating` — upsert the caller's score/review (`docs/api.md`). */
export async function putRating(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
  body: RatingInput,
): Promise<ApiResult<Rating>> {
  switch (type) {
    case "movie":
      return client.PUT("/v1/movies/{slug}/rating", { params: { path: { slug } }, body, headers });
    case "series":
      return client.PUT("/v1/series/{slug}/rating", { params: { path: { slug } }, body, headers });
    case "book":
      return client.PUT("/v1/books/{slug}/rating", { params: { path: { slug } }, body, headers });
    case "game":
      return client.PUT("/v1/games/{slug}/rating", { params: { path: { slug } }, body, headers });
  }
}

/** `DELETE /v1/{type}/{slug}/rating` — remove the caller's own rating (`docs/api.md`). */
export async function deleteRating(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
): Promise<ApiResult<undefined>> {
  switch (type) {
    case "movie":
      return client.DELETE("/v1/movies/{slug}/rating", { params: { path: { slug } }, headers });
    case "series":
      return client.DELETE("/v1/series/{slug}/rating", { params: { path: { slug } }, headers });
    case "book":
      return client.DELETE("/v1/books/{slug}/rating", { params: { path: { slug } }, headers });
    case "game":
      return client.DELETE("/v1/games/{slug}/rating", { params: { path: { slug } }, headers });
  }
}

/**
 * `GET /v1/{type}/{slug}/ratings?page=&limit=` — public, paginated, newest
 * first (`docs/api.md`). No dedicated "my rating" endpoint exists (see
 * `progress/current.md`): the `GET /api/{type}/{slug}/rating` Route Handler
 * calls this with the maximum page size and scans for the caller's own
 * username to recover their current score/review as this widget's initial
 * state. FE-19's `GET /api/{type}/{slug}/ratings` Route Handler
 * (`app/api/[type]/[slug]/ratings/route.ts`) calls this too, for the actual
 * paginated reviews listing on the item detail page.
 *
 * `headers` is optional (defaults to `{}`, i.e. no `Authorization` header) —
 * the endpoint itself never requires auth. But since each item's
 * `liked_by_viewer` (round-2 QA fix, `progress/current.md`) is resolved by
 * the backend from the caller's bearer token when one is present, callers
 * that know the viewer's identity should still forward it here so the
 * response reflects that viewer's real like state instead of always
 * resolving to an anonymous `false`.
 */
export async function listRatings(
  client: ApiClient,
  type: CatalogType,
  slug: string,
  query: { page?: number; limit?: number } = {},
  headers: Record<string, string> = {},
): Promise<ApiResult<RatingPage>> {
  switch (type) {
    case "movie":
      return client.GET("/v1/movies/{slug}/ratings", { params: { path: { slug }, query }, headers });
    case "series":
      return client.GET("/v1/series/{slug}/ratings", { params: { path: { slug }, query }, headers });
    case "book":
      return client.GET("/v1/books/{slug}/ratings", { params: { path: { slug }, query }, headers });
    case "game":
      return client.GET("/v1/games/{slug}/ratings", { params: { path: { slug }, query }, headers });
  }
}

/**
 * `POST /v1/ratings/{rating_id}/like` — like a review (FE-19). Idempotent,
 * auth required, 204 no body (`docs/api.md`). `{rating_id}` is the review's
 * own numeric id (`user_ratings.id`, not a slug), same id `ReportReviewButton`
 * already uses for `POST /v1/reviews/{rating_id}/report`.
 */
export async function likeReview(
  client: ApiClient,
  headers: Record<string, string>,
  ratingId: number,
): Promise<ApiResult<undefined>> {
  return client.POST("/v1/ratings/{rating_id}/like", {
    params: { path: { rating_id: ratingId } },
    headers,
  });
}

/**
 * `DELETE /v1/ratings/{rating_id}/like` — remove the caller's own like from a
 * review (FE-19). Idempotent, auth required, 204 no body (`docs/api.md`).
 */
export async function unlikeReview(
  client: ApiClient,
  headers: Record<string, string>,
  ratingId: number,
): Promise<ApiResult<undefined>> {
  return client.DELETE("/v1/ratings/{rating_id}/like", {
    params: { path: { rating_id: ratingId } },
    headers,
  });
}
