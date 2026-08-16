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
 * POST /api/admin/reviews/{id}/unhide
 *
 * Proxies `POST /v1/admin/reviews/{rating_id}/unhide` (FE-30, `docs/api.md`):
 * restores a previously hidden review. Mirrors `../hide/route.ts` exactly —
 * see that file's doc comment for the shared pattern/rationale.
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
      "/v1/admin/reviews/{rating_id}/unhide",
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

    return NextResponse.json({ error: "unhide_review_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/reviews/[id]/unhide: failed to reach the API", error);
    return NextResponse.json({ error: "unhide_review_failed" }, { status: 502 });
  }
}
