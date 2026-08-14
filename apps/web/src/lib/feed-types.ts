/**
 * Framework-agnostic activity feed vocabulary (FE-23): the `tab` value union
 * plus a runtime mirror and type guard for it. No `server-only` import
 * (directly or transitively) — safe to import from components that don't
 * themselves need to fetch (e.g. `src/components/feed-tabs.tsx`,
 * `src/components/feed-pagination.tsx`, both plain server-rendered `Link`
 * components with no fetch of their own), same split rationale as
 * `./library-types.ts` vs `./library.ts` / `./catalog-types.ts` vs
 * `./catalog.ts`.
 *
 * `./feed.ts` holds the actual data-fetching function (`getFeed`) and
 * re-exports everything here for convenience — but it also imports
 * `apiFetch` (`./api-fetch.ts`), which starts with `import "server-only"`.
 */

export type FeedTab = "following" | "popular";

export const FEED_TABS: readonly FeedTab[] = ["following", "popular"];

export const DEFAULT_FEED_TAB: FeedTab = "following";

/** Type guard for a raw query param (e.g. `/feed?tab=`) against {@link FeedTab}. Anything else — including missing/garbled input — is treated as {@link DEFAULT_FEED_TAB} by callers, never forwarded to the backend as-is. */
export function isFeedTab(value: string): value is FeedTab {
  return (FEED_TABS as readonly string[]).includes(value);
}
