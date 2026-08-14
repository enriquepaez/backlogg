import type { ApiClient, components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";

/**
 * Follow/unfollow helpers (FE-23). Same two-shape split as `./library.ts`
 * and `./ratings.ts`:
 *
 * - `followUser`/`unfollowUser` take `client`/`headers` explicitly (same
 *   dispatch shape as `./ratings.ts`'s `likeReview`/`unlikeReview` — no
 *   per-type switch needed, `/v1/users/{username}/follow` is a single
 *   templated path) — these back the auth-required BFF route
 *   (`src/app/api/users/[username]/follow/route.ts`).
 * - `getFollowers`/`getFollowing` are self-contained (own `getApiClient()`,
 *   own try/catch, `ok`-tagged result) because both backing endpoints are
 *   public — same house style as `./library.ts`'s `getUserLibrary`. The
 *   `/u/{username}/followers` and `/u/{username}/following` pages call
 *   these directly.
 *
 * There is no dedicated "am I following {username}" endpoint (same class of
 * gap as `./ratings.ts`'s "no dedicated my-rating endpoint" doc comment) —
 * `GET /api/users/{username}/follow` (the BFF route) works around this by
 * calling `getFollowing` for the *viewer's own* username with the maximum
 * page size and scanning for the target username, same "single page scan"
 * trade-off `listRatings`'s caller already accepts.
 */

export type FollowUser = components["schemas"]["FollowUserOut"];

type ApiResult<T> = { data?: T; response: Response };

/** `POST /v1/users/{username}/follow` — idempotent, auth required (`docs/api.md`). */
export async function followUser(
  client: ApiClient,
  headers: Record<string, string>,
  username: string,
): Promise<ApiResult<undefined>> {
  return client.POST("/v1/users/{username}/follow", { params: { path: { username } }, headers });
}

/** `DELETE /v1/users/{username}/follow` — idempotent, auth required (`docs/api.md`). */
export async function unfollowUser(
  client: ApiClient,
  headers: Record<string, string>,
  username: string,
): Promise<ApiResult<undefined>> {
  return client.DELETE("/v1/users/{username}/follow", { params: { path: { username } }, headers });
}

export type FollowQuery = { page?: number; limit?: number };

export type FollowPageResult =
  | { ok: true; items: FollowUser[]; total: number; page: number; limit: number }
  | { ok: false };

/** `GET /v1/users/{username}/followers?page=&limit=` — public, paginated (`docs/api.md`). */
export async function getFollowers(
  username: string,
  query: FollowQuery = {},
): Promise<FollowPageResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/followers", {
      params: { path: { username }, query },
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getFollowers(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}

/** `GET /v1/users/{username}/following?page=&limit=` — public, paginated (`docs/api.md`). */
export async function getFollowing(
  username: string,
  query: FollowQuery = {},
): Promise<FollowPageResult> {
  try {
    const { data, response } = await getApiClient().GET("/v1/users/{username}/following", {
      params: { path: { username }, query },
    });
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error(`getFollowing(${username}): failed to reach the API`, error);
    return { ok: false };
  }
}
