import type { ApiClient, components } from "@backlogg/api-client";

import type { CatalogType } from "./catalog-types";

/**
 * Server-side dispatch helpers for the activity log endpoints (FE-41,
 * backend feature 52 — `docs/api.md`'s "Activity log" section), used only
 * from Route Handlers (`src/app/api/[type]/[slug]/log/route.ts`,
 * `src/app/api/log/[id]/route.ts`) — never imported by a Client Component.
 * Same per-type switch shape as `./ratings.ts`/`./library.ts`: the generated
 * client exposes one operation per literal path (`/v1/movies/{slug}/log`,
 * `/v1/series/{slug}/log`, ...), so there is no single templated call across
 * all four catalog types.
 *
 * Unlike `.../rating` and `.../library`, a log entry is never an upsert — a
 * user can have multiple logs for the same item (`docs/api.md`) — so there
 * is no per-item "current" log to fetch by slug alone. `getUserLog` (public,
 * cross-type, `GET /v1/users/{username}/log`) is the only backend surface
 * that can answer "this user's own logs", which the `GET /api/{type}/{slug}/log`
 * Route Handler uses (filtered client-side to the current item) to build the
 * "your log history for this item" section — see that route's doc comment.
 */

export type LogEntry = components["schemas"]["LogOut"];
export type LogPage = components["schemas"]["LogListOut"];
export type UserLogEntry = components["schemas"]["UserLogOut"];
export type UserLogPage = components["schemas"]["UserLogListOut"];
export type LogInput = { logged_on?: string | null; rewatch: boolean; note?: string | null };

/**
 * One of the caller's own log entries for a single item — the shape
 * `GET /api/{type}/{slug}/log`'s `mine` field returns and `ActivityLogWidget`
 * renders. Deliberately narrower than {@link LogEntry}/{@link UserLogEntry}
 * (no `item_type`/`slug`/`item`/`created_at`): the widget already knows
 * which item it's showing history for, so those fields would be redundant.
 */
export type MyLogEntry = { id: number; logged_on: string; rewatch: boolean; note: string | null };

type ApiResult<T> = { data?: T; response: Response };

/** `POST /v1/{type}/{slug}/log` — create a new log entry for the caller (`docs/api.md`). */
export async function postLog(
  client: ApiClient,
  headers: Record<string, string>,
  type: CatalogType,
  slug: string,
  body: LogInput,
): Promise<ApiResult<LogEntry>> {
  switch (type) {
    case "movie":
      return client.POST("/v1/movies/{slug}/log", { params: { path: { slug } }, body, headers });
    case "series":
      return client.POST("/v1/series/{slug}/log", { params: { path: { slug } }, body, headers });
    case "book":
      return client.POST("/v1/books/{slug}/log", { params: { path: { slug } }, body, headers });
    case "game":
      return client.POST("/v1/games/{slug}/log", { params: { path: { slug } }, body, headers });
  }
}

/** `GET /v1/{type}/{slug}/log?page=&limit=` — public, paginated log entries for the item (`docs/api.md`). */
export async function listLog(
  client: ApiClient,
  type: CatalogType,
  slug: string,
  query: { page?: number; limit?: number } = {},
): Promise<ApiResult<LogPage>> {
  switch (type) {
    case "movie":
      return client.GET("/v1/movies/{slug}/log", { params: { path: { slug }, query } });
    case "series":
      return client.GET("/v1/series/{slug}/log", { params: { path: { slug }, query } });
    case "book":
      return client.GET("/v1/books/{slug}/log", { params: { path: { slug }, query } });
    case "game":
      return client.GET("/v1/games/{slug}/log", { params: { path: { slug }, query } });
  }
}

/** `DELETE /v1/log/{log_id}` — remove the caller's own log entry (`docs/api.md`). */
export async function deleteLog(
  client: ApiClient,
  headers: Record<string, string>,
  logId: number,
): Promise<ApiResult<undefined>> {
  return client.DELETE("/v1/log/{log_id}", {
    params: { path: { log_id: logId } },
    headers,
  });
}

/**
 * `GET /v1/users/{username}/log?page=&limit=` — public, paginated, cross-type
 * log history for a user (`docs/api.md`). No `{type, slug}` filter exists on
 * this endpoint; callers that need "this user's logs for one specific item"
 * (the `GET /api/{type}/{slug}/log` Route Handler) fetch the largest allowed
 * page and filter client-side — see that route's doc comment for the known
 * limitation this implies.
 */
export async function getUserLog(
  client: ApiClient,
  username: string,
  query: { page?: number; limit?: number } = {},
): Promise<ApiResult<UserLogPage>> {
  return client.GET("/v1/users/{username}/log", {
    params: { path: { username }, query },
  });
}
