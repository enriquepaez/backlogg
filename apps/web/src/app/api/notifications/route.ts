import { NextResponse } from "next/server";

import { getNotifications } from "@/lib/notifications";

/** Default/maximum page size — same values as `GET /api/{type}/{slug}/ratings` (`../[type]/[slug]/ratings/route.ts`), the closest precedent for a small, dropdown-sized paginated listing. */
const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 100;

function parsePositiveInt(raw: string | null, fallback: number, max?: number): number {
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return fallback;
  }
  return max ? Math.min(parsed, max) : parsed;
}

/**
 * GET /api/notifications?page=&limit=
 *
 * Proxies `GET /v1/notifications` (`docs/api.md`) for `NotificationBell`
 * (`src/components/notification-bell.tsx`) — a Client Component, so it can't
 * call `@/lib/notifications` (transitively `server-only`) itself. Calls
 * `getNotifications` directly rather than going through `apiFetch` here a
 * second time: that self-contained helper already wraps it (same shape as
 * `getFeed`, `@/lib/feed.ts`), and Route Handlers — unlike Server Component
 * render — allow its 401 refresh to persist the rotated cookies (see
 * `@/lib/notifications`'s doc comment).
 *
 * Auth required on the backend, so an `ok: false` result here almost always
 * means "no valid session" (this route is only ever called by the bell,
 * itself only rendered for a signed-in `navUser` — `site-header.tsx`) or a
 * genuine upstream failure; both degrade the same way client-side (silently
 * hide/empty the dropdown), so there is no need to distinguish them with a
 * more specific status than 502.
 */
export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const page = parsePositiveInt(url.searchParams.get("page"), 1);
  const limit = parsePositiveInt(url.searchParams.get("limit"), DEFAULT_LIMIT, MAX_LIMIT);

  const result = await getNotifications({ page, limit });
  if (!result.ok) {
    return NextResponse.json({ error: "list_notifications_failed" }, { status: 502 });
  }

  const { items, total, page: resultPage, limit: resultLimit } = result;
  return NextResponse.json({ items, total, page: resultPage, limit: resultLimit }, { status: 200 });
}
