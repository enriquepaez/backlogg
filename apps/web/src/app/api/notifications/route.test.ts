// @vitest-environment node
//
// `getNotifications` (`@/lib/notifications`) is mocked so this file only
// exercises the route's own branching (query parsing, error passthrough),
// same rationale/shape as `../[type]/[slug]/ratings/route.test.ts` mocking
// `listRatings`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const getNotificationsMock = vi.fn();
vi.mock("@/lib/notifications", () => ({
  getNotifications: (...args: unknown[]) => getNotificationsMock(...args),
}));

const { GET } = await import("./route");

function request(query = ""): Request {
  return new Request(`http://localhost:3000/api/notifications${query}`);
}

const page = {
  items: [
    {
      id: 1,
      type: "new_follower",
      actor: { username: "bob", display_name: "Bob", avatar_url: null },
      target: { target_type: null, target_id: null, item_type: null, slug: null },
      is_read: false,
      created_at: "2026-05-25T18:04:11Z",
    },
  ],
  total: 1,
  page: 1,
  limit: 10,
};

beforeEach(() => {
  getNotificationsMock.mockClear();
});

describe("GET /api/notifications", () => {
  it("defaults to page=1, limit=10 with no query params", async () => {
    getNotificationsMock.mockResolvedValueOnce({ ok: true, ...page });

    await GET(request());

    expect(getNotificationsMock).toHaveBeenCalledWith({ page: 1, limit: 10 });
  });

  it("forwards valid page/limit query params", async () => {
    getNotificationsMock.mockResolvedValueOnce({ ok: true, ...page });

    await GET(request("?page=2&limit=25"));

    expect(getNotificationsMock).toHaveBeenCalledWith({ page: 2, limit: 25 });
  });

  it.each(["0", "-1", "1.5", "abc"])("falls back to page=1 for an invalid page value %p", async (raw) => {
    getNotificationsMock.mockResolvedValueOnce({ ok: true, ...page });

    await GET(request(`?page=${raw}`));

    expect(getNotificationsMock).toHaveBeenCalledWith({ page: 1, limit: 10 });
  });

  it("caps limit at 100 even when a larger value is requested", async () => {
    getNotificationsMock.mockResolvedValueOnce({ ok: true, ...page });

    await GET(request("?limit=1000"));

    expect(getNotificationsMock).toHaveBeenCalledWith({ page: 1, limit: 100 });
  });

  it("returns 200 with the page data on success", async () => {
    getNotificationsMock.mockResolvedValueOnce({ ok: true, ...page });

    const response = await GET(request());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(page);
  });

  it("returns 502 when the underlying fetch fails", async () => {
    getNotificationsMock.mockResolvedValueOnce({ ok: false });

    const response = await GET(request());
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "list_notifications_failed" });
  });
});
