import type { CatalogType } from "@/lib/catalog-types";

/**
 * Central TanStack Query key factory for the "personal widgets" (FE-48):
 * the viewer's own rating, their library/backlog status, their activity log
 * history, notifications, and the public per-status library counts shown on
 * a profile page. Before this feature each of `rating-widget.tsx`,
 * `viewer-status-slot.tsx`, `activity-log-widget.tsx` and
 * `notification-bell.tsx` reimplemented its own `useState` + `useEffect` +
 * `fetch` — no shared cache, no cross-widget invalidation, and no vocabulary
 * for query identity. Centralizing the key shapes here (rather than each
 * widget inlining its own array) is what makes the FE-48 acceptance
 * criterion "completar un item en el item detail invalida `library_counts`
 * del perfil" possible at all: `viewer-status-slot.tsx` (which changes a
 * status) and `library-status-counts.tsx` (which reads the aggregate counts
 * on `/u/{username}`) live in unrelated component trees/routes and share no
 * props — the only thing that lets one invalidate the other is agreeing on
 * the same key shape, defined once, here.
 *
 * Nested `{ all, byX() }` groups (the `library.counts` shape below) follow
 * the common TanStack Query "key factory" convention: `all` is a plain
 * prefix array, `byUsername(...)` extends it. Since `invalidateQueries`
 * matches by prefix by default, `queryClient.invalidateQueries({ queryKey:
 * queryKeys.library.counts.all })` invalidates every `byUsername(...)` query
 * currently cached, regardless of which username's suffix it carries — the
 * mechanism `viewer-status-slot.tsx` relies on. It doesn't know (and has no
 * cheap way to know) which profile the caller is looking at, so it
 * invalidates the whole `library.counts` family rather than a single
 * username: only the viewer's own profile can ever actually be affected by
 * the viewer's own status change, and it's the only such query realistically
 * mounted in the same browser session, so the extra breadth costs at most an
 * unnecessary (but harmless, idempotent) refetch of someone else's profile
 * counts in the rare case one happens to be mounted too.
 */
export const queryKeys = {
  rating: {
    /** The viewer's own rating for one item — backs `GET /api/{type}/{slug}/rating`. */
    detail: (type: CatalogType, slug: string) => ["rating", type, slug] as const,
  },
  library: {
    /** The viewer's own backlog status for one item — backs `GET /api/{type}/{slug}/library`. */
    status: (type: CatalogType, slug: string) => ["library", "status", type, slug] as const,
    counts: {
      /** Prefix shared by every `byUsername(...)` key — never fetched directly, only used to invalidate the whole family (see this module's doc comment). */
      all: ["library", "counts"] as const,
      /** Per-status library counts for one user's public profile — backs `GET /api/users/{username}/library_counts`. */
      byUsername: (username: string) => ["library", "counts", username] as const,
    },
  },
  /** The viewer's own activity log history for one item — backs `GET /api/{type}/{slug}/log`. */
  activityLog: {
    detail: (type: CatalogType, slug: string) => ["activity-log", type, slug] as const,
  },
  notifications: {
    /** Backs `GET /api/notifications/unread_count` (the header bell's badge). */
    unreadCount: ["notifications", "unread-count"] as const,
    /** Backs `GET /api/notifications?page=&limit=` (the dropdown's list). */
    list: (page: number, limit: number) => ["notifications", "list", page, limit] as const,
  },
};
