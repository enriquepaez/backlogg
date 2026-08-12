import type { ApiClient, components } from "@backlogg/api-client";

import type { CatalogType } from "./catalog-types";

/**
 * Server-side dispatch helpers for the ratings endpoints (FE-18), used only
 * from Route Handlers (`src/app/api/[type]/[slug]/rating/route.ts`) — never
 * imported by a Client Component. Same reasoning/shape as `./catalog.ts`'s
 * per-type switches (`getItemDetail`, `getFeatured`, ...): the generated
 * client exposes one operation per literal path (`/v1/movies/{slug}/rating`,
 * `/v1/series/{slug}/rating`, ...), so there is no single templated call to
 * make across all four catalog types.
 *
 * Each function returns the exact `{ data?, response }` shape `apiFetch`
 * (`src/lib/api-fetch.ts`) expects from the callback it wraps — `putRating`/
 * `deleteRating` are meant to be passed straight through to `apiFetch` so an
 * expired access token is transparently refreshed once, same as every other
 * authenticated BFF route. `listRatings` is public (no auth token, mirrors
 * `docs/api.md`: `GET /v1/{type}/{slug}/ratings` requires no bearer token)
 * so it takes a plain `ApiClient` instead.
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
 * state.
 */
export async function listRatings(
  client: ApiClient,
  type: CatalogType,
  slug: string,
  query: { page?: number; limit?: number } = {},
): Promise<ApiResult<RatingPage>> {
  switch (type) {
    case "movie":
      return client.GET("/v1/movies/{slug}/ratings", { params: { path: { slug }, query } });
    case "series":
      return client.GET("/v1/series/{slug}/ratings", { params: { path: { slug }, query } });
    case "book":
      return client.GET("/v1/books/{slug}/ratings", { params: { path: { slug }, query } });
    case "game":
      return client.GET("/v1/games/{slug}/ratings", { params: { path: { slug }, query } });
  }
}
