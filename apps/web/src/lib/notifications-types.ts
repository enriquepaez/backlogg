import { toCatalogType } from "@/lib/catalog-types";

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
 *
 * The single import below, `@/lib/catalog-types`, is safe on that count: it
 * is the other framework-agnostic vocabulary module and has zero imports of
 * its own. Since issue #33 it owns `toCatalogType`, which this file used to
 * duplicate as a private `notificationItemType`.
 */

export type NotificationItem = components["schemas"]["NotificationOut"];

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
 *   four known catalog types — `toCatalogType` takes the nullable
 *   `target.item_type` directly and returns `undefined` for both cases. Shouldn't happen once the backend always
 *   resolves them for `review_like` (see `progress/impl_notifications_
 *   backend.md`), but the frontend stays defensive rather than link to
 *   `/null/undefined`.
 * - `user_completed` (FE-42) → the completed item, resolved from
 *   `target.item_type`/`target.slug` exactly like `review_like` — per
 *   `docs/api.md`, the backend already resolves both fields the same way for
 *   this type (`target_id` differs — it's the item's own id, not a rating's —
 *   but this function never reads `target_id`, so that difference doesn't
 *   matter here).
 * - Any other/future `type` → `undefined`, same "no link" fallback.
 */
export function notificationHref(notification: NotificationItem): string | undefined {
  if (notification.type === "new_follower") {
    return `/u/${notification.actor.username}`;
  }
  if (notification.type === "review_like" || notification.type === "user_completed") {
    const type = toCatalogType(notification.target.item_type);
    const slug = notification.target.slug;
    return type && slug ? `/${type}/${slug}` : undefined;
  }
  return undefined;
}
