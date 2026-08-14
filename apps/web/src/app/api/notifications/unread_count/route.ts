import { NextResponse } from "next/server";

import { getUnreadCount } from "@/lib/notifications";

/**
 * GET /api/notifications/unread_count
 *
 * Proxies `GET /v1/notifications/unread_count` (`docs/api.md`) for
 * `NotificationBell` (a Client Component — see `../route.ts`'s doc comment
 * for why this can't call `@/lib/notifications` directly). Backs the badge's
 * initial count on mount and its refresh right after `POST
 * /api/notifications/read` (FE-24 acceptance: "... refresca el badge").
 */
export async function GET(): Promise<NextResponse> {
  const result = await getUnreadCount();
  if (!result.ok) {
    return NextResponse.json({ error: "unread_count_failed" }, { status: 502 });
  }

  return NextResponse.json({ unread_count: result.unread_count }, { status: 200 });
}
