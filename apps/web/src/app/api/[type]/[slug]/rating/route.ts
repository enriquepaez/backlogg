import { revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

import { apiFetch, getCurrentUser } from "@/lib/api-fetch";
import { authHeader, getApiClient } from "@/lib/auth/session";
import { itemDetailCacheTag } from "@/lib/catalog";
import { isCatalogType } from "@/lib/catalog-types";
import { deleteRating, listRatings, putRating, type Rating, type RatingInput } from "@/lib/ratings";

type RouteParams = { params: Promise<{ type: string; slug: string }> };

/**
 * `GET /v1/{type}/{slug}/ratings?limit=` returns at most this many rows
 * (backend caps `limit` at 100, `docs/api.md`) — the widest single-page scan
 * `GET`'s "find my own rating" workaround (see doc comment below) can do.
 */
const MY_RATING_SCAN_LIMIT = 100;

type PutPayload = { score?: unknown; review_text?: unknown };

function isValidScore(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 5);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/**
 * GET /api/{type}/{slug}/rating
 *
 * There is no dedicated "my rating" endpoint on the backend (see
 * `progress/current.md`) — `ItemDetail` (`GET /v1/{type}/{slug}`) doesn't
 * expose the viewer's own rating, only `viewer_status` (library, FE-20).
 * This proxies the public `GET /v1/{type}/{slug}/ratings` (no auth
 * required) with the maximum page size and scans it for an entry matching
 * the caller's own `username`, reusing `getCurrentUser()` (the FE-4/FE-14
 * session check, `src/lib/api-fetch.ts`) to identify the caller.
 *
 * Known limitation: this only ever looks at the first
 * {@link MY_RATING_SCAN_LIMIT} ratings (newest first). On an item with more
 * than 100 ratings, a caller's own older rating can fall off that first
 * page and this reports `rating: null` even though one exists — the rating
 * widget (`rating-widget.tsx`) then starts in "no rating yet" state, and a
 * subsequent `PUT` still upserts the caller's existing row correctly (same
 * (user, item) unique row, `docs/schema.md`), it just silently replaces
 * whatever `review_text` was there before instead of showing it back for
 * editing. Acceptable for now — no better contract exists — flagged for
 * FE-19 (`reviews_display_likes`) to reconsider once a paginated "my
 * reviews" surface exists.
 *
 * Always 200 (never 401) so the item detail page's rating widget can render
 * an anonymous "log in to rate" prompt itself, distinguished via the
 * `authenticated` flag, instead of treating "no session" as a request
 * failure.
 */
export async function GET(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json({ authenticated: false, rating: null }, { status: 200 });
  }

  const { data, response } = await listRatings(getApiClient(), type, slug, {
    limit: MY_RATING_SCAN_LIMIT,
  });

  if (response.status !== 200 || !data) {
    return NextResponse.json(
      { error: "list_ratings_failed" },
      { status: response.status || 500 },
    );
  }

  const mine = data.items.find((item) => item.user.username === user.username) ?? null;
  return NextResponse.json({ authenticated: true, rating: mine }, { status: 200 });
}

/**
 * PUT /api/{type}/{slug}/rating
 *
 * Proxies `PUT /v1/{type}/{slug}/rating` (`RatingIn` in, `RatingOut` out —
 * `docs/api.md`): full replace (upsert), not a partial patch — the caller
 * (`rating-widget.tsx`) always sends both fields. Uses `apiFetch` (FE-4) for
 * transparent access-token refresh, same pattern as `users/me/route.ts`.
 *
 * Bugfix (post-FE-18 QA): calls `revalidateTag(itemDetailCacheTag(...), {
 * expire: 0 })` on a successful upsert so the item detail page's cached
 * `rating_internal`/`rating_count_internal` (`getItemDetail`,
 * `src/lib/catalog.ts`) don't stay stale for up to an hour after the
 * caller's own score changes them — see {@link itemDetailCacheTag}'s doc
 * comment. `{ expire: 0 }` (immediate expiration), not the `"max"` profile
 * Next 16's own docs otherwise recommend (`stale-while-revalidate`: the tag
 * is only marked stale, fresh data isn't guaranteed until *some later*
 * visit) — this route needs the *very next* reload of the page the caller
 * is looking at to already be fresh, which is exactly the documented use
 * case for `{ expire: 0 }` (`node_modules/next/dist/docs/.../revalidateTag.md`:
 * "For webhooks or third-party services that need immediate expiration").
 * `updateTag` (the alternative Next suggests for immediate,
 * read-your-own-writes invalidation) is Server-Action-only and cannot be
 * called from a Route Handler.
 */
export async function PUT(request: Request, { params }: RouteParams): Promise<NextResponse> {
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

  const { score, review_text: reviewText } = (payload as PutPayload) ?? {};
  if (!isValidScore(score) || !isNullableString(reviewText)) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const body: RatingInput = { score, review_text: reviewText };

  const { data, response } = await apiFetch<Rating>((client, token) =>
    putRating(client, authHeader(token), type, slug, body),
  );

  if (response.status === 200 && data) {
    revalidateTag(itemDetailCacheTag(type, slug), { expire: 0 });
    return NextResponse.json(data, { status: 200 });
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

  return NextResponse.json({ error: "rate_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/{type}/{slug}/rating
 *
 * Proxies `DELETE /v1/{type}/{slug}/rating` (204, no body — `docs/api.md`).
 * Same `apiFetch` auto-refresh as `PUT` above, and the same post-FE-18
 * `revalidateTag` bugfix (deleting the caller's rating changes the item's
 * aggregates too).
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const { response } = await apiFetch<undefined>((client, token) =>
    deleteRating(client, authHeader(token), type, slug),
  );

  if (response.status === 204) {
    revalidateTag(itemDetailCacheTag(type, slug), { expire: 0 });
    return new NextResponse(null, { status: 204 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "delete_rating_failed" }, { status: response.status || 500 });
}
