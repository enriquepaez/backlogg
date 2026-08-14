import type { components } from "@backlogg/api-client";

import { apiFetch } from "./api-fetch";
import { authHeader } from "./auth/session";
import { notificationHref, notificationItemType, type NotificationItem } from "./notifications-types";

/**
 * Notifications data source (FE-24): `GET /v1/notifications`,
 * `GET /v1/notifications/unread_count`, `POST /v1/notifications/read` — all
 * auth required (`docs/api.md`). Same skeleton as `./feed.ts`: built on
 * `apiFetch`, which reads the access-token cookie and retries once through a
 * refresh on a 401, safe to call directly from Server Component render (see
 * that module's doc comment) AND from Route Handlers (which additionally
 * allow `apiFetch`'s refresh to persist the rotated cookies, unlike render —
 * see `./auth/session.ts`'s `safeSet`). The three BFF routes under
 * `src/app/api/notifications/` call these directly for `NotificationBell`
 * (a Client Component, which can't import this module itself — see its doc
 * comment).
 *
 * No `import "server-only"` of its own — same as `./feed.ts`/`./library.ts`/
 * `./ratings.ts`: the guard already lives in `./api-fetch.ts`/
 * `./auth/session.ts`, both imported here, so this module inherits it
 * transitively rather than redeclaring it.
 */

export type { NotificationItem };
export { notificationHref, notificationItemType };

type NotificationListOut = components["schemas"]["NotificationListOut"];
type UnreadCountOut = components["schemas"]["UnreadCountOut"];

export type NotificationQuery = { page?: number; limit?: number };

export type NotificationPageResult =
  | { ok: true; items: NotificationItem[]; total: number; page: number; limit: number }
  | { ok: false };

/** `GET /v1/notifications?page=&limit=` — the caller's own notifications, paginated, newest first (`docs/api.md`). */
export async function getNotifications(query: NotificationQuery = {}): Promise<NotificationPageResult> {
  try {
    const { data, response } = await apiFetch<NotificationListOut>((client, token) =>
      client.GET("/v1/notifications", {
        params: { query: { page: query.page, limit: query.limit } },
        headers: authHeader(token),
      }),
    );
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error("getNotifications: failed to reach the API", error);
    return { ok: false };
  }
}

export type UnreadCountResult = { ok: true; unread_count: number } | { ok: false };

/** `GET /v1/notifications/unread_count` — number of unread notifications for the caller (`docs/api.md`). */
export async function getUnreadCount(): Promise<UnreadCountResult> {
  try {
    const { data, response } = await apiFetch<UnreadCountOut>((client, token) =>
      client.GET("/v1/notifications/unread_count", { headers: authHeader(token) }),
    );
    return response.status === 200 && data ? { ok: true, unread_count: data.unread_count } : { ok: false };
  } catch (error) {
    console.error("getUnreadCount: failed to reach the API", error);
    return { ok: false };
  }
}

export type MarkReadPayload = { ids?: number[] };

/**
 * `POST /v1/notifications/read` — marks notifications read (idempotent,
 * `docs/api.md`). `ids` omitted marks every unread notification of the
 * caller; `ids` provided marks only those.
 */
export async function markRead(payload: MarkReadPayload = {}): Promise<{ ok: boolean }> {
  try {
    const { response } = await apiFetch<undefined>((client, token) =>
      client.POST("/v1/notifications/read", {
        body: payload.ids ? { ids: payload.ids } : undefined,
        headers: authHeader(token),
      }),
    );
    return { ok: response.status === 204 };
  } catch (error) {
    console.error("markRead: failed to reach the API", error);
    return { ok: false };
  }
}

/**
 * `DELETE /v1/notifications/{id}` — deletes one of the caller's own
 * notifications (204). 404 if it doesn't exist or isn't theirs (`docs/api.md`)
 * — surfaced here simply as `ok: false`, same as every other non-2xx/network
 * failure in this module.
 */
export async function deleteNotification(id: number): Promise<{ ok: boolean }> {
  try {
    const { response } = await apiFetch<undefined>((client, token) =>
      client.DELETE("/v1/notifications/{notification_id}", {
        params: { path: { notification_id: id } },
        headers: authHeader(token),
      }),
    );
    return { ok: response.status === 204 };
  } catch (error) {
    console.error("deleteNotification: failed to reach the API", error);
    return { ok: false };
  }
}
