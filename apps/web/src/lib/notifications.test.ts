// @vitest-environment node
//
// `getNotifications`/`getUnreadCount`/`markRead` are built on `apiFetch`
// (`@/lib/api-fetch`), which depends on `next/headers`' request-scoped
// `cookies()` and only works inside a real Next.js request — same rationale
// as `feed.test.ts`: mock `apiFetch`/`authHeader` directly rather than
// exercise the real cookie-reading/refresh machinery. `notificationHref`/
// `notificationItemType` are plain re-exports of `./notifications-types.ts`
// — tested here (rather than in a dedicated `notifications-types.test.ts`)
// the same way `feed.test.ts` covers `isFeedTab` alongside the fetch
// helpers in `./feed.ts`.
import { describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const {
  getNotifications,
  getUnreadCount,
  markRead,
  deleteNotification,
  notificationHref,
  notificationItemType,
} = await import("./notifications");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

const newFollowerNotification = {
  id: 1,
  type: "new_follower",
  actor: { username: "bob", display_name: "Bob", avatar_url: null },
  target: { target_type: null, target_id: null, item_type: null, slug: null },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const reviewLikeNotification = {
  id: 2,
  type: "review_like",
  actor: { username: "carol", display_name: null, avatar_url: null },
  target: { target_type: "review", target_id: 512, item_type: "MOVIE", slug: "the-matrix-1999" },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

describe("notificationItemType", () => {
  it("lowercases a known uppercase item_type", () => {
    expect(notificationItemType("MOVIE")).toBe("movie");
    expect(notificationItemType("GAME")).toBe("game");
  });

  it("returns undefined for null or an unknown value", () => {
    expect(notificationItemType(null)).toBeUndefined();
    expect(notificationItemType("SHOW")).toBeUndefined();
  });
});

describe("notificationHref", () => {
  it("links new_follower to the actor's profile", () => {
    expect(notificationHref(newFollowerNotification)).toBe("/u/bob");
  });

  it("links review_like to the target item, not the actor's profile", () => {
    expect(notificationHref(reviewLikeNotification)).toBe("/movie/the-matrix-1999");
  });

  it("returns undefined for review_like when the slug is missing (defensive)", () => {
    expect(
      notificationHref({
        ...reviewLikeNotification,
        target: { ...reviewLikeNotification.target, slug: null },
      }),
    ).toBeUndefined();
  });

  it("returns undefined for review_like when item_type is missing (defensive)", () => {
    expect(
      notificationHref({
        ...reviewLikeNotification,
        target: { ...reviewLikeNotification.target, item_type: null },
      }),
    ).toBeUndefined();
  });
});

const notificationPage = {
  items: [reviewLikeNotification],
  total: 1,
  page: 1,
  limit: 10,
};

describe("getNotifications", () => {
  it("returns ok with the paginated items on a 200, forwarding page/limit and the bearer header", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          GET: vi.fn().mockResolvedValue({ data: notificationPage, response: backendResponse(200) }),
        };
        const result = await call(client, "the-token");
        expect(client.GET).toHaveBeenCalledWith("/v1/notifications", {
          params: { query: { page: 1, limit: 10 } },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await getNotifications({ page: 1, limit: 10 })).toEqual({ ok: true, ...notificationPage });
  });

  it("returns ok: false on a 401 (no valid session)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    expect(await getNotifications()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await getNotifications()).toEqual({ ok: false });
  });
});

describe("getUnreadCount", () => {
  it("returns ok with the count on a 200", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          GET: vi.fn().mockResolvedValue({ data: { unread_count: 3 }, response: backendResponse(200) }),
        };
        const result = await call(client, "the-token");
        expect(client.GET).toHaveBeenCalledWith("/v1/notifications/unread_count", {
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await getUnreadCount()).toEqual({ ok: true, unread_count: 3 });
  });

  it("returns ok: false on a 401", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    expect(await getUnreadCount()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await getUnreadCount()).toEqual({ ok: false });
  });
});

describe("markRead", () => {
  it("posts with no body to mark all as read, returning ok: true on a 204", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          POST: vi.fn().mockResolvedValue({ response: backendResponse(204) }),
        };
        const result = await call(client, "the-token");
        expect(client.POST).toHaveBeenCalledWith("/v1/notifications/read", {
          body: undefined,
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await markRead()).toEqual({ ok: true });
  });

  it("posts with ids to mark only those as read", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          POST: vi.fn().mockResolvedValue({ response: backendResponse(204) }),
        };
        const result = await call(client, "the-token");
        expect(client.POST).toHaveBeenCalledWith("/v1/notifications/read", {
          body: { ids: [1, 2] },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await markRead({ ids: [1, 2] })).toEqual({ ok: true });
  });

  it("returns ok: false on a non-204 response", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    expect(await markRead()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await markRead()).toEqual({ ok: false });
  });
});

describe("deleteNotification", () => {
  it("deletes by id, returning ok: true on a 204", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          DELETE: vi.fn().mockResolvedValue({ response: backendResponse(204) }),
        };
        const result = await call(client, "the-token");
        expect(client.DELETE).toHaveBeenCalledWith("/v1/notifications/{notification_id}", {
          params: { path: { notification_id: 7 } },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await deleteNotification(7)).toEqual({ ok: true });
  });

  it("returns ok: false on a 404 (not found or not the caller's)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    expect(await deleteNotification(7)).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await deleteNotification(7)).toEqual({ ok: false });
  });
});
