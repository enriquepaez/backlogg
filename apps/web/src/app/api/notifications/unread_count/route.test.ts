// @vitest-environment node
//
// `getUnreadCount` (`@/lib/notifications`) is mocked so this file only
// exercises the route's own thin passthrough.
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUnreadCountMock = vi.fn();
vi.mock("@/lib/notifications", () => ({
  getUnreadCount: (...args: unknown[]) => getUnreadCountMock(...args),
}));

const { GET } = await import("./route");

beforeEach(() => {
  getUnreadCountMock.mockClear();
});

describe("GET /api/notifications/unread_count", () => {
  it("returns 200 with the count on success", async () => {
    getUnreadCountMock.mockResolvedValueOnce({ ok: true, unread_count: 5 });

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ unread_count: 5 });
  });

  it("returns 502 when the underlying fetch fails", async () => {
    getUnreadCountMock.mockResolvedValueOnce({ ok: false });

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "unread_count_failed" });
  });
});
