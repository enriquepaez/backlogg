// @vitest-environment node
//
// `deleteNotification` (`@/lib/notifications`) is mocked so this file only
// exercises the route's own id validation/branching — same rationale as
// `../read/route.test.ts`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const deleteNotificationMock = vi.fn();
vi.mock("@/lib/notifications", () => ({
  deleteNotification: (...args: unknown[]) => deleteNotificationMock(...args),
}));

const { DELETE } = await import("./route");

function params(id: string) {
  return { params: Promise.resolve({ id }) };
}

beforeEach(() => {
  deleteNotificationMock.mockClear();
});

describe("DELETE /api/notifications/{id}", () => {
  it.each(["not-a-number", "-1", "1.5", ""])("returns 400 for an invalid id %p", async (id) => {
    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params(id));

    expect(response.status).toBe(400);
    expect(deleteNotificationMock).not.toHaveBeenCalled();
  });

  it("forwards the numeric id and returns 204 on success", async () => {
    deleteNotificationMock.mockResolvedValueOnce({ ok: true });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));

    expect(deleteNotificationMock).toHaveBeenCalledWith(7);
    expect(response.status).toBe(204);
  });

  it("returns 502 when the underlying call fails (not found, not the caller's, or network)", async () => {
    deleteNotificationMock.mockResolvedValueOnce({ ok: false });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "delete_notification_failed" });
  });
});
