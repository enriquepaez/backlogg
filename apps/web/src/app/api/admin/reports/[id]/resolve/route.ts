import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RouteParams = { params: Promise<{ id: string }> };

function parseReportId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * POST /api/admin/reports/{id}/resolve
 *
 * Proxies `POST /v1/admin/reports/{report_id}/resolve` (FE-29, `docs/api.md`):
 * marks a report resolved. Idempotent on the backend (repeat calls for an
 * already-resolved report still return 200 with the same `status`), so this
 * route doesn't special-case a repeat call either. Same base pattern as
 * `../../stats/route.ts` and `../route.ts` — `ADMIN_API_KEY` is read and
 * injected as `X-API-Key` here, server-side ONLY; `AdminReportsPanel`
 * (`@/components/admin-reports-panel.tsx`), the only caller, never sees it.
 *
 * `{id}` is the report's own numeric id (`ReportOut.id`), not the reported
 * rating's id — same distinction `../../reviews/[id]/report/route.ts` draws
 * for its own `{id}` (there, a rating id; here, a report id).
 *
 * Status mapping extends `../route.ts`/`../../stats/route.ts` with 404 (the
 * one response this endpoint has that the read-only ones don't, per
 * `docs/api.md`: "404 if unknown"): this app's own `ADMIN_API_KEY` unset ->
 * 503; backend 401 -> 401; backend 404 -> 404; backend 503 -> 503; anything
 * else -> 502.
 */
export async function POST(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const reportId = parseReportId(id);
  if (reportId === null) {
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
      "/v1/admin/reports/{report_id}/resolve",
      {
        params: {
          header: { "x-api-key": apiKey },
          path: { report_id: reportId },
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

    return NextResponse.json({ error: "resolve_report_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/reports/[id]/resolve: failed to reach the API", error);
    return NextResponse.json({ error: "resolve_report_failed" }, { status: 502 });
  }
}
