import { NextResponse } from "next/server";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { deleteLog } from "@/lib/activity-log";

type RouteParams = { params: Promise<{ id: string }> };

function parseLogId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * DELETE /api/log/{id}
 *
 * Proxies `DELETE /v1/log/{log_id}` (204, no body — `docs/api.md`): removes
 * one of the caller's own log entries. `{id}` is the log entry's own numeric
 * id (not a slug — a single item can have many logs, `docs/api.md`), same
 * "id-keyed action under its own top-level `/api/log/`" convention as
 * `POST /api/reviews/{id}/like` (`app/api/reviews/[id]/like/route.ts`), which
 * groups by a similar id-only backend action rather than nesting under
 * `{type}/{slug}`. Uses `apiFetch` (FE-4) for transparent access-token
 * refresh, same pattern as every other authenticated BFF route.
 *
 * 404 covers both "no such log entry" and "exists but belongs to another
 * user" — the backend collapses both to keep from leaking which is which
 * (`docs/api.md`).
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const logId = parseLogId(id);
  if (logId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const { response } = await apiFetch<undefined>((client, token) => deleteLog(client, authHeader(token), logId));

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "delete_log_failed" }, { status: response.status || 500 });
}
