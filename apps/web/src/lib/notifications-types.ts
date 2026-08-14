import { isCatalogType, type CatalogType } from "@/lib/catalog-types";

import type { components } from "@backlogg/api-client";

/**
 * Framework-agnostic notifications vocabulary (FE-24): the `NotificationItem`
 * shape plus the linking rules for it. No `server-only` import (directly or
 * transitively) — safe to import from Client Components (`notification-
 * bell.tsx` needs this at render time to build each entry's link, same as
 * `src/components/feed-tabs.tsx` needing `./feed-types.ts`), same split
 * rationale as `./feed-types.ts` vs `./feed.ts` / `./library-types.ts` vs
 * `./library.ts`.
 *
 * `./notifications.ts` holds the actual data-fetching functions and
 * re-exports everything here for convenience — but it also imports
 * `apiFetch` (`./api-fetch.ts`), which starts with `import "server-only"`.
 */

export type NotificationItem = components["schemas"]["NotificationOut"];

/**
 * Maps the backend's uppercase `NotificationTargetOut.item_type`
 * (`"MOVIE"`/`"SERIES"`/`"BOOK"`/`"GAME"`) to the route-segment `CatalogType`
 * used to link to `/{type}/{slug}`. Same logic as `feedItemType`
 * (`@/components/feed-entry-list.tsx`) / `toCatalogType` (`@/lib/search.ts`),
 * duplicated rather than imported — same "small, self-contained helper beats
 * an awkward cross-module dependency" rationale those two document, doubly
 * true here since `notification-bell.tsx` is a Client Component and can't
 * pull in `./search.ts` (transitively `server-only`) at all.
 */
export function notificationItemType(itemType: string | null): CatalogType | undefined {
  if (!itemType) {
    return undefined;
  }
  const lower = itemType.toLowerCase();
  return isCatalogType(lower) ? lower : undefined;
}

/**
 * Builds the link target for a single notification (FE-24 acceptance:
 * "Tipos new_follower/review_like enlazan al destino correcto"):
 *
 * - `new_follower` → the actor's public profile (`/u/{username}`); there is
 *   no `target` to speak of (`target.*` is always `null` for this type,
 *   `docs/api.md`).
 * - `review_like` → the exact item the liked review is about
 *   (`/{item_type}/{slug}`, lowercased — same `` `/${type}/${slug}` `` shape
 *   as `browse/[type]/page.tsx`/`item-similar.tsx`), NOT the profile of the
 *   user who liked the review — a product decision already made (see
 *   `progress/current.md`). Returns `undefined` (no link — callers must not
 *   render this notification as clickable) if `target.slug`/`target.
 *   item_type` are missing, or resolve to something other than one of the
 *   four known catalog types. Shouldn't happen once the backend always
 *   resolves them for `review_like` (see `progress/impl_notifications_
 *   backend.md`), but the frontend stays defensive rather than link to
 *   `/null/undefined`.
 * - Any other/future `type` → `undefined`, same "no link" fallback.
 */
export function notificationHref(notification: NotificationItem): string | undefined {
  if (notification.type === "new_follower") {
    return `/u/${notification.actor.username}`;
  }
  if (notification.type === "review_like") {
    const type = notificationItemType(notification.target.item_type);
    const slug = notification.target.slug;
    return type && slug ? `/${type}/${slug}` : undefined;
  }
  return undefined;
}
