import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";

type ReportReasonIn = components["schemas"]["ReportReasonIn"];
type ReportOut = components["schemas"]["ReportOut"];

type RouteParams = { params: Promise<{ id: string }> };

function parseRatingId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * POST /api/reviews/{id}/report
 *
 * Proxies `POST /v1/reviews/{rating_id}/report` (`ReportReasonIn | null` in,
 * `ReportOut` out — `docs/api.md`). `{id}` is the rating's own numeric id
 * (`user_ratings.id`), not a slug — see `ReportReviewButton`, which is the
 * only caller today, mounted from `rating-widget.tsx` against the viewer's
 * own just-saved rating (FE-18's scope has no other review surfaced on the
 * item detail page yet — the full reviews listing is FE-19).
 *
 * Idempotent per (reporter, review): the backend returns 201 the first time
 * and 200 on every repeat call for the same pair, `reason` unchanged either
 * way (`docs/api.md`). Both are forwarded as-is (not collapsed to a single
 * status) so the caller can tell a brand-new report apart from "you already
 * reported this" if it ever wants to, though `ReportReviewButton` currently
 * treats them the same (a disabled, already-reported affordance).
 *
 * Uses `apiFetch` (FE-4) for transparent access-token refresh, same pattern
 * as every other authenticated BFF route.
 */
export async function POST(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const ratingId = parseRatingId(id);
  if (ratingId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const rawBody = await request.text();
  let reason: string | null = null;
  if (rawBody) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawBody);
    } catch {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    const candidate = (parsed as { reason?: unknown } | null)?.reason;
    if (candidate !== undefined && candidate !== null && typeof candidate !== "string") {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    reason = (candidate as string | undefined) ?? null;
  }

  const body: ReportReasonIn = { reason };

  const { data, response } = await apiFetch<ReportOut>((client, token) =>
    client.POST("/v1/reviews/{rating_id}/report", {
      params: { path: { rating_id: ratingId } },
      body,
      headers: authHeader(token),
    }),
  );

  if (response.status === 201 && data) {
    return NextResponse.json({ id: data.id, created: true }, { status: 201 });
  }
  if (response.status === 200) {
    return NextResponse.json({ id: data?.id, created: false }, { status: 200 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "report_failed" }, { status: response.status || 500 });
}
