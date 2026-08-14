import type { components } from "@backlogg/api-client";

import { apiFetch } from "./api-fetch";
import { authHeader } from "./auth/session";
import { DEFAULT_FEED_TAB, FEED_TABS, isFeedTab, type FeedTab } from "./feed-types";

/**
 * Activity feed data source (FE-23), `GET /v1/feed?tab=&page=&limit=` —
 * auth required (`docs/api.md`). Unlike the public per-user endpoints in
 * `./library.ts`/`./follows.ts`/`./user-content.ts` (which own their own
 * `getApiClient()` call, no token to attach), this needs the caller's own
 * bearer token — same shape as `getCurrentUser` (`./api-fetch.ts`): built on
 * `apiFetch`, which reads the access-token cookie, retries once through a
 * refresh on a 401, and is safe to call directly from Server Component
 * render (see that module's doc comment).
 *
 * No `import "server-only"` of its own — same as `./library.ts`/
 * `./ratings.ts`/`./user-content.ts`: the guard already lives in
 * `./api-fetch.ts`/`./auth/session.ts`, both imported here, so this module
 * inherits it transitively rather than redeclaring it.
 */

export type { FeedTab };
export { DEFAULT_FEED_TAB, FEED_TABS, isFeedTab };

export type FeedEntry = components["schemas"]["FeedEntryOut"];
type FeedListOut = components["schemas"]["FeedListOut"];

export type FeedQuery = {
  tab: FeedTab;
  page?: number;
  limit?: number;
};

export type FeedPageResult =
  | { ok: true; items: FeedEntry[]; total: number; page: number; limit: number }
  | { ok: false };

/**
 * `GET /v1/feed?tab=&page=&limit=`. `tab` is always one of {@link FeedTab}
 * (enforced by the type itself, never a raw string) so this never sends the
 * backend an invalid `tab` and never triggers its 422 — satisfying FE-23's
 * "an invalid tab must not be reachable from the UI" acceptance criterion at
 * the call site rather than by handling a 422 response here.
 */
export async function getFeed(query: FeedQuery): Promise<FeedPageResult> {
  try {
    const { data, response } = await apiFetch<FeedListOut>((client, token) =>
      client.GET("/v1/feed", {
        params: { query: { tab: query.tab, page: query.page, limit: query.limit } },
        headers: authHeader(token),
      }),
    );
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error("getFeed: failed to reach the API", error);
    return { ok: false };
  }
}
