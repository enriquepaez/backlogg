import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

/**
 * Public, per-user content for the profile page (FE-21): reviews across all
 * four content types. Split from `./library.ts` (which already owns
 * `getUserProfile`/`getUserLibrary`) rather than folded into it — that
 * file's own doc comment scopes it to library/backlog, and this endpoint is
 * a distinct slice of `UserOut`-adjacent public data with its own response
 * shape. Same house style as `getUserLibrary`/`getUserProfile` though: this
 * helper owns its `getApiClient()` call and its own try/catch, no BFF proxy
 * needed, because the backing endpoint is public (`docs/api.md`).
 */

export type UserReview = components["schemas"]["UserReviewOut"];

export type UserReviewsResult =
  | { ok: true; items: UserReview[]; total: number; page: number; limit: number }
  | { ok: false };

export type UserReviewsQuery = {
  page?: number;
  limit?: number;
};

/**
 * `GET /v1/users/{username}/reviews?page=&limit=` — public, paginated,
 * cross-type (UNION ALL of movies/series/books/games, `docs/api.md`). Same
 * `ok`-tagged result shape as `./library.ts`'s `getUserLibrary`: a failure is
 * reported explicitly rather than silently degrading to an empty section.
 */
export async function getUserReviews(
  username: string,
  query: UserReviewsQuery = {},
): Promise<UserReviewsResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/reviews", {
      params: { path: { username }, query },
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getUserReviews(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}
