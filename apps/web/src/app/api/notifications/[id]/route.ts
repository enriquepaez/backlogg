import { NextResponse } from "next/server";

import { deleteNotification } from "@/lib/notifications";

type RouteParams = { params: Promise<{ id: string }> };

function parseNotificationId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) {
    return null;
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * DELETE /api/notifications/{id}
 *
 * Proxies `DELETE /v1/notifications/{id}` (204, auth required — `docs/api.md`)
 * for `NotificationBell` (a Client Component, so it can't call
 * `@/lib/notifications` itself — see `../route.ts`'s doc comment). Calls
 * `deleteNotification` directly rather than going through `apiFetch` here a
 * second time, same rationale as `GET`/`POST` in the sibling routes under
 * `src/app/api/notifications/`. `{id}` is the notification's own numeric id
 * — same validation pattern as `api/reviews/[id]/like/route.ts`.
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { id } = await params;
  const notificationId = parseNotificationId(id);
  if (notificationId === null) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const result = await deleteNotification(notificationId);
  if (!result.ok) {
    return NextResponse.json({ error: "delete_notification_failed" }, { status: 502 });
  }

  return new NextResponse(null, { status: 204 });
}
