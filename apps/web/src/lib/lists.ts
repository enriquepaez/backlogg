import type { ApiClient, components } from "@backlogg/api-client";

/**
 * Server-side dispatch helpers for the lists CRUD endpoints (FE-25):
 * `createList`/`updateList`/`deleteList`. Same `client`/`headers`-explicit
 * shape as `./follows.ts`'s `followUser`/`unfollowUser` and `./library.ts`'s
 * `putLibraryStatus`/`deleteLibraryStatus` — all three back the FE-25 BFF
 * routes (`src/app/api/lists/route.ts`, `src/app/api/lists/[slug]/route.ts`)
 * which need `apiFetch`'s token-refresh dance around the actual call, so each
 * function here is meant to be passed straight through to `apiFetch` rather
 * than called directly.
 *
 * All three endpoints are single templated paths (`/v1/lists`,
 * `/v1/lists/{slug}`) — unlike `./library.ts`/`./ratings.ts`'s per-catalog-type
 * switches, there is only one content type ("a list"), so no dispatch switch
 * is needed here.
 */

export type UserListDetail = components["schemas"]["UserListOut"];
export type ListCreateInput = components["schemas"]["ListCreate"];
export type ListUpdateInput = components["schemas"]["ListUpdate"];

type ApiResult<T> = { data?: T; response: Response };

/** `POST /v1/lists` — create a list; slug derived from the title (`docs/api.md`). */
export async function createList(
  client: ApiClient,
  headers: Record<string, string>,
  body: ListCreateInput,
): Promise<ApiResult<UserListDetail>> {
  return client.POST("/v1/lists", { body, headers });
}

/** `PATCH /v1/lists/{slug}` — update title/description/is_public; owner only (`docs/api.md`). */
export async function updateList(
  client: ApiClient,
  headers: Record<string, string>,
  slug: string,
  body: ListUpdateInput,
): Promise<ApiResult<UserListDetail>> {
  return client.PATCH("/v1/lists/{slug}", { params: { path: { slug } }, body, headers });
}

/** `DELETE /v1/lists/{slug}` — delete the list and cascade its items; owner only (`docs/api.md`). */
export async function deleteList(
  client: ApiClient,
  headers: Record<string, string>,
  slug: string,
): Promise<ApiResult<undefined>> {
  return client.DELETE("/v1/lists/{slug}", { params: { path: { slug } }, headers });
}
