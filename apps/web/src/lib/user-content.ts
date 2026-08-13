import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

/**
 * Public, per-user content for the profile page (FE-21): reviews across all
 * four content types and public lists. Split from `./library.ts` (which
 * already owns `getUserProfile`/`getUserLibrary`) rather than folded into
 * it — that file's own doc comment scopes it to library/backlog, and these
 * two endpoints are a distinct slice of `UserOut`-adjacent public data with
 * their own response shapes. Same house style as `getUserLibrary`/
 * `getUserProfile` though: both helpers here own their `getApiClient()` call
 * and their own try/catch, no BFF proxy needed, because both backing
 * endpoints are public (`docs/api.md`).
 */

export type UserReview = components["schemas"]["UserReviewOut"];
export type UserListSummary = components["schemas"]["UserListSummary"];

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

export type UserListsResult =
  | { ok: true; lists: UserListSummary[]; total: number }
  | { ok: false };

/**
 * `GET /v1/users/{username}/lists` — auth-optional (`docs/api.md`: public
 * lists always visible, private ones only to their owner), but called here
 * without a bearer token, same as every other fetch in this public profile
 * page (`getUserProfile`, `getUserLibrary`) — none of them attach the
 * viewer's own session, matching `getItemDetail`'s established pattern of
 * never personalizing a plain server-rendered page fetch (`./catalog.ts`).
 * The practical effect: this always returns only `{username}`'s *public*
 * lists, even when the viewer is the owner — acceptable for FE-21's scope
 * ("listas públicas visibles"), private-list visibility for the owner is
 * FE-25/26 territory once list detail pages exist to link to.
 */
export async function getUserLists(username: string): Promise<UserListsResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/lists", {
      params: { path: { username } },
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getUserLists(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}
