import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type ReportStatus = components["schemas"]["ReportStatus"];

/** Same values as `../notifications/route.ts` (`docs/api.md`'s `GET /v1/admin/reports` default/max `limit`). */
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

function parsePositiveInt(raw: string | null, fallback: number, max?: number): number {
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return fallback;
  }
  return max ? Math.min(parsed, max) : parsed;
}

function parseStatus(raw: string | null): ReportStatus | undefined {
  return raw === "open" || raw === "resolved" ? raw : undefined;
}

/**
 * GET /api/admin/reports?status=&page=&limit=
 *
 * Proxies `GET /v1/admin/reports` (FE-29, `docs/api.md`): the moderation
 * queue of reported reviews, newest first, optionally filtered by
 * `status` (`open`/`resolved`). Same base pattern as `../stats/route.ts` —
 * this app's own `ADMIN_API_KEY` (`@/lib/env`, `server-only`) is read here,
 * server-side ONLY, and injected as `X-API-Key` on the call to the backend.
 * `AdminReportsPanel` (`@/components/admin-reports-panel.tsx`), the only
 * caller, is a Client Component that talks to this route, never to the
 * backend directly, so the key never reaches the browser.
 *
 * `status` is validated against the two known values here rather than
 * forwarded as-is: an unrecognized value is treated as "no filter" (omitted
 * from the backend call) instead of risking a 422 from the backend for a
 * typo'd query param, same defensive spirit as `parsePositiveInt` below
 * falling back instead of erroring on a malformed `page`/`limit`.
 *
 * No user-session check here on purpose — see `../stats/route.ts`'s doc
 * comment: `/v1/admin/*` auth is entirely the shared `X-API-Key` secret, and
 * the real authorization (signed-in AND `user.is_admin`) already happened in
 * the page that renders `AdminReportsPanel` (`/admin`,
 * `@/app/[locale]/admin/page.tsx`).
 *
 * Status mapping mirrors `../stats/route.ts`: this app's own `ADMIN_API_KEY`
 * unset -> 503; backend 401 -> 401; backend 503 -> 503; anything else -> 502.
 */
export async function GET(request: Request): Promise<NextResponse> {
  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  const url = new URL(request.url);
  const status = parseStatus(url.searchParams.get("status"));
  const page = parsePositiveInt(url.searchParams.get("page"), 1);
  const limit = parsePositiveInt(url.searchParams.get("limit"), DEFAULT_LIMIT, MAX_LIMIT);

  try {
    const { data, response } = await getApiClient().GET("/v1/admin/reports", {
      params: {
        header: { "x-api-key": apiKey },
        query: { status, page, limit },
      },
    });

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "admin_reports_failed" }, { status: 502 });
  } catch (error) {
    console.error("GET /api/admin/reports: failed to reach the API", error);
    return NextResponse.json({ error: "admin_reports_failed" }, { status: 502 });
  }
}
