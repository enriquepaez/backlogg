import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RouteParams = { params: Promise<{ id: string }> };

function parseRatingId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * POST /api/admin/reviews/{id}/hide
 *
 * Proxies `POST /v1/admin/reviews/{rating_id}/hide` (FE-30, `docs/api.md`):
 * hides a review from public listings, the feed and the rating aggregates.
 * `{id}` is the review's own numeric id (`user_ratings.id`), same convention
 * as `../../report/route.ts`'s `{id}`. Same base pattern as
 * `../../../reports/[id]/resolve/route.ts` — only the shared `X-API-Key` is
 * required (no caller session), read server-side ONLY from `@/lib/env` and
 * injected here; `AdminReportsPanel` (`@/components/admin-reports-panel.tsx`),
 * the only caller, never sees it.
 *
 * Idempotent on the backend (`docs/api.md`), so no special-casing for a
 * repeat call. Status mapping mirrors `../../../reports/[id]/resolve/route.ts`:
 * this app's own `ADMIN_API_KEY` unset -> 503; backend 401 -> 401; backend
 * 404 -> 404; anything else -> 502.
 */
export async function POST(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const ratingId = parseRatingId(id);
  if (ratingId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  try {
    const { data, response } = await getApiClient().POST(
      "/v1/admin/reviews/{rating_id}/hide",
      {
        params: {
          header: { "x-api-key": apiKey },
          path: { rating_id: ratingId },
        },
      },
    );

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 404) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "hide_review_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/reviews/[id]/hide: failed to reach the API", error);
    return NextResponse.json({ error: "hide_review_failed" }, { status: 502 });
  }
}
