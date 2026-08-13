import { NextResponse } from "next/server";

import { getCurrentUser } from "@/lib/api-fetch";
import { getApiClient } from "@/lib/auth/session";
import { isCatalogType } from "@/lib/catalog-types";
import { listRatings } from "@/lib/ratings";

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
 * does (`../rating/route.ts`): the list itself never needs the caller's
 * identity, only whether `ItemReviews` (`src/components/item-reviews.tsx`)
 * should let the viewer click "like" or send them to `/login` instead — the
 * backend's `POST`/`DELETE /v1/ratings/{id}/like` both require auth.
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

  const [user, { data, response }] = await Promise.all([
    getCurrentUser(),
    listRatings(getApiClient(), type, slug, { page, limit }),
  ]);

  if (response.status !== 200 || !data) {
    return NextResponse.json(
      { error: "list_ratings_failed" },
      { status: response.status || 500 },
    );
  }

  return NextResponse.json({ authenticated: user !== null, ...data }, { status: 200 });
}
