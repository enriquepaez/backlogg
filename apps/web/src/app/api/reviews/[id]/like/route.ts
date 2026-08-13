import { NextResponse } from "next/server";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { likeReview, unlikeReview } from "@/lib/ratings";

type RouteParams = { params: Promise<{ id: string }> };

function parseRatingId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * POST /api/reviews/{id}/like
 *
 * Proxies `POST /v1/ratings/{rating_id}/like` (204, no body — `docs/api.md`).
 * `{id}` is the review's own numeric id (`user_ratings.id`, not a slug),
 * same convention as `POST /api/reviews/{id}/report` (`../report/route.ts`)
 * — grouped under `/api/reviews/` even though the backend itself splits the
 * two actions across `/v1/reviews/*` (report) and `/v1/ratings/*` (like):
 * both are "an action on a specific review, keyed by its id", the BFF
 * surface FE-18 already established for this id.
 *
 * Idempotent on the backend (`docs/api.md`); `ItemReviews`
 * (`src/components/item-reviews.tsx`) is the only caller today, driving its
 * own optimistic UI with revert-on-failure — this route stays a thin proxy
 * using `apiFetch` (FE-4) for transparent access-token refresh, same as
 * every other authenticated BFF route.
 */
export async function POST(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const ratingId = parseRatingId(id);
  if (ratingId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const { response } = await apiFetch<undefined>((client, token) =>
    likeReview(client, authHeader(token), ratingId),
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "like_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/reviews/{id}/like
 *
 * Proxies `DELETE /v1/ratings/{rating_id}/like` — same shape/rationale as
 * `POST` above.
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const ratingId = parseRatingId(id);
  if (ratingId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const { response } = await apiFetch<undefined>((client, token) =>
    unlikeReview(client, authHeader(token), ratingId),
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "unlike_failed" }, { status: response.status || 500 });
}
