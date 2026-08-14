import { NextResponse } from "next/server";

import { markRead } from "@/lib/notifications";

type ReadPayload = { ids?: unknown };

function parseIds(payload: ReadPayload): number[] | undefined {
  if (!Array.isArray(payload.ids)) {
    return undefined;
  }
  const ids = payload.ids.filter(
    (id): id is number => typeof id === "number" && Number.isInteger(id),
  );
  return ids.length > 0 ? ids : undefined;
}

/**
 * POST /api/notifications/read
 *
 * Proxies `POST /v1/notifications/read` (204, idempotent — `docs/api.md`)
 * for `NotificationBell` (a Client Component — see `../route.ts`'s doc
 * comment for why this can't call `@/lib/notifications` directly). Body is
 * optional: an empty/missing body (or `ids` omitted/not-an-array) marks
 * every unread notification of the caller; a body with `ids` marks only
 * those. `NotificationBell` always calls this with no body (mark-all) when
 * the dropdown is opened — see that component's doc comment for why.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: ReadPayload = {};
  try {
    payload = ((await request.json()) as ReadPayload) ?? {};
  } catch {
    // Empty body is the common case (mark-all) — not an error.
  }

  const result = await markRead({ ids: parseIds(payload) });
  if (!result.ok) {
    return NextResponse.json({ error: "mark_read_failed" }, { status: 502 });
  }

  return new NextResponse(null, { status: 204 });
}
