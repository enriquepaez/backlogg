import { NextResponse } from "next/server";

import {
  getUserLog,
  listLog,
  postLog,
  type LogEntry,
  type LogInput,
  type MyLogEntry,
} from "@/lib/activity-log";
import { apiFetch, getCurrentUser } from "@/lib/api-fetch";
import { authHeader, getApiClient } from "@/lib/auth/session";
import { isCatalogType } from "@/lib/catalog-types";

type RouteParams = { params: Promise<{ type: string; slug: string }> };

/**
 * `GET /v1/users/{username}/log?limit=` returns at most this many rows
 * (backend caps `limit` at 100, `docs/api.md`) — the widest single-page scan
 * this route's "find my own logs for this item" workaround (see doc comment
 * below) can do. Same rationale/precedent as `MY_RATING_SCAN_LIMIT` in
 * `app/api/[type]/[slug]/rating/route.ts`.
 */
const MY_LOG_SCAN_LIMIT = 100;

type PostPayload = { logged_on?: unknown; rewatch?: unknown; note?: unknown };

function isNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

/**
 * GET /api/{type}/{slug}/log
 *
 * Proxies the public `GET /v1/{type}/{slug}/log?page=&limit=` (item-scoped,
 * every user's log entries, newest `logged_on` first — `docs/api.md`) and
 * forwards its `items`/`total`/`page`/`limit` verbatim.
 *
 * Also resolves the caller's *own* log history for this item, under `mine` —
 * something the item-scoped endpoint above cannot do on its own: `LogOut`
 * (each row of that listing) carries no author, so there is no way to tell
 * which of an item's logs belong to the viewer (unlike `RatingOut`, which
 * carries `user`, letting `GET /api/{type}/{slug}/rating` scan-and-match by
 * username — see that route's doc comment). The only backend surface scoped
 * to "one user's own logs" is `GET /v1/users/{username}/log` (public,
 * cross-type, no `{type, slug}` filter — `docs/api.md`), so this route calls
 * it with the caller's own username (via `getCurrentUser()`, FE-4/FE-14) and
 * the largest allowed page size, then filters client-side to entries whose
 * `item.item_type`/`item.slug` match this route's own `{type}`/`{slug}`.
 *
 * Known limitation, mirroring `MY_RATING_SCAN_LIMIT`'s: this only ever scans
 * the caller's first {@link MY_LOG_SCAN_LIMIT} log entries *across every
 * item* (newest `logged_on` first). A caller with more than 100 total log
 * entries can have older logs for *this* item fall off that page and
 * `ActivityLogWidget` would then under-report their history for it. No
 * `{type, slug}` filter exists on `GET /v1/users/{username}/log` today to
 * avoid this — flagged here for a future backend change (an optional item
 * filter on that endpoint) rather than worked around with unbounded
 * pagination from a Route Handler.
 *
 * Always 200 (never 401) so `ActivityLogWidget` can render its own anonymous
 * "log in" prompt for the create form, distinguished via `authenticated`,
 * same pattern as `GET /api/{type}/{slug}/rating`/`GET /api/{type}/{slug}/library`.
 */
export async function GET(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const url = new URL(request.url);
  const query: { page?: number; limit?: number } = {};
  const page = url.searchParams.get("page");
  const limit = url.searchParams.get("limit");
  if (page) query.page = Number(page);
  if (limit) query.limit = Number(limit);

  const { data, response } = await listLog(getApiClient(), type, slug, query);
  if (response.status !== 200 || !data) {
    if (response.status === 404) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    if (response.status === 422) {
      return NextResponse.json({ error: "validation_error" }, { status: 422 });
    }
    return NextResponse.json({ error: "list_log_failed" }, { status: response.status || 500 });
  }

  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json({ ...data, authenticated: false, mine: [] }, { status: 200 });
  }

  const { data: userLogData, response: userLogResponse } = await getUserLog(getApiClient(), user.username, {
    limit: MY_LOG_SCAN_LIMIT,
  });

  const backendType = type.toUpperCase();
  const mine: MyLogEntry[] =
    userLogResponse.status === 200 && userLogData
      ? userLogData.items
          .filter((entry) => entry.item.item_type.toUpperCase() === backendType && entry.item.slug === slug)
          .map((entry) => ({ id: entry.id, logged_on: entry.logged_on, rewatch: entry.rewatch, note: entry.note }))
      : [];

  return NextResponse.json({ ...data, authenticated: true, mine }, { status: 200 });
}

/**
 * POST /api/{type}/{slug}/log
 *
 * Proxies `POST /v1/{type}/{slug}/log` (`LogIn` in, `LogOut` out —
 * `docs/api.md`): always creates a new log entry, never an upsert. Uses
 * `apiFetch` (FE-4) for transparent access-token refresh, same pattern as
 * `PUT /api/{type}/{slug}/rating`.
 *
 * `logged_on` defaults to today on the backend when omitted/`null`;
 * `rewatch` defaults to `false`; `note` defaults to `null`. No
 * `revalidateTag` needed here (unlike the rating route's bugfix): log
 * entries don't feed into any of `ItemDetail`'s cached aggregates.
 */
export async function POST(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { logged_on: loggedOn, rewatch, note } = (payload as PostPayload) ?? {};
  if (!isNullableString(loggedOn) || !isNullableString(note) || (rewatch !== undefined && typeof rewatch !== "boolean")) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const body: LogInput = {
    logged_on: loggedOn ?? null,
    rewatch: rewatch ?? false,
    note: note ?? null,
  };

  const { data, response } = await apiFetch<LogEntry>((client, token) =>
    postLog(client, authHeader(token), type, slug, body),
  );

  if (response.status === 201 && data) {
    return NextResponse.json(data, { status: 201 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json({ error: "log_failed" }, { status: response.status || 500 });
}
