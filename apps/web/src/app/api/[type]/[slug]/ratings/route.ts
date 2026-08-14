import { NextResponse } from "next/server";

import { apiFetch, getCurrentUser } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { isCatalogType } from "@/lib/catalog-types";
import { listRatings, type RatingPage } from "@/lib/ratings";

type RouteParams = { params: Promise<{ type: string; slug: string }> };

/** Default/maximum page size for the reviews listing (backend caps `limit` at 100, `docs/api.md`). */
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
 * GET /api/{type}/{slug}/ratings?page=&limit=
 *
 * Public reviews listing for the item detail page (FE-19 acceptance:
 * "GET /v1/{tipo}/{slug}/ratings paginado con like_count; reviews ocultas no
 * aparecen"). Proxies `GET /v1/{type}/{slug}/ratings` (`docs/api.md`) as-is
 * — reviews hidden by moderation are already excluded server-side, nothing
 * to filter here.
 *
 * Also reports whether the caller has an active session (`authenticated`),
 * reusing `getCurrentUser()` the same way `GET /api/{type}/{slug}/rating`
 * does (`../rating/route.ts`): besides identity, this also gates whether
 * `ItemReviews` (`src/components/item-reviews.tsx`) should let the viewer
 * click "like" or send them to `/login` instead — the backend's
 * `POST`/`DELETE /v1/ratings/{id}/like` both require auth.
 *
 * `listRatings` itself is called through `apiFetch` (not a bare
 * `getApiClient()` call) even though the endpoint never requires
 * auth — round-2 QA fix (`progress/current.md`): each item's
 * `liked_by_viewer` is resolved by the backend from the caller's bearer
 * token when one is present (`docs/api.md`), so an authenticated caller's
 * token must still be forwarded for that field to reflect reality instead of
 * always resolving to an anonymous `false`. Sequenced *after* `getCurrentUser()`
 * (not run in parallel via `Promise.all` like before) so that if the access
 * token was expired, `getCurrentUser()`'s own `apiFetch` call already
 * refreshed and rewrote the cookies first — otherwise this call could read
 * the same stale token in a race and still resolve `liked_by_viewer: false`
 * for a viewer who does have a valid (refreshable) session.
 *
 * Always 200 for a valid page request (mirrors the public backend endpoint):
 * the caller distinguishes "not authenticated" from "no reviews yet" via the
 * response body, not the status code.
 */
export async function GET(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const url = new URL(request.url);
  const page = parsePositiveInt(url.searchParams.get("page"), 1);
  const limit = parsePositiveInt(url.searchParams.get("limit"), DEFAULT_LIMIT, MAX_LIMIT);

  const user = await getCurrentUser();
  const { data, response } = await apiFetch<RatingPage>((client, token) =>
    listRatings(client, type, slug, { page, limit }, authHeader(token)),
  );

  if (response.status !== 200 || !data) {
    return NextResponse.json(
      { error: "list_ratings_failed" },
      { status: response.status || 500 },
    );
  }

  return NextResponse.json({ authenticated: user !== null, ...data }, { status: 200 });
}
