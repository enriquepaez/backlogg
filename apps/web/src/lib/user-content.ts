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
 * lists always visible, private ones only to their owner).
 *
 * `headers` is optional (defaults to `{}`, i.e. no `Authorization` header),
 * same shape as `./ratings.ts`'s `listRatings`: the endpoint never requires
 * auth, but the backend resolves "is the caller the owner" from the bearer
 * token when one is present (`get_current_user_optional`,
 * `backlogg/users/auth.py` — an absent/invalid/expired token is treated as
 * anonymous, never a 401), so a caller that knows the viewer's session must
 * forward it here for private lists to surface when the viewer IS the owner.
 * `/u/{username}/page.tsx` (FE-21/FE-25) does this after resolving
 * `getCurrentUser()`, forwarding the (possibly just-refreshed) access token
 * unconditionally — safe even for a viewer who isn't `{username}`, since the
 * backend only ever adds *that same viewer's own* private lists to the
 * response, never anyone else's.
 *
 * Previously called with no headers at all (FE-21 original scope: "listas
 * públicas visibles"), which meant the owner never saw their own private
 * lists on their own profile — closed by FE-25 now that create/edit/delete
 * controls exist and need private lists to actually appear for their owner.
 */
export async function getUserLists(
  username: string,
  headers: Record<string, string> = {},
): Promise<UserListsResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/lists", {
      params: { path: { username } },
      headers,
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getUserLists(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}
