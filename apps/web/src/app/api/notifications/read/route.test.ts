// @vitest-environment node
//
// `markRead` (`@/lib/notifications`) is mocked so this file only exercises
// the route's own body parsing.
import { beforeEach, describe, expect, it, vi } from "vitest";

const markReadMock = vi.fn();
vi.mock("@/lib/notifications", () => ({
  markRead: (...args: unknown[]) => markReadMock(...args),
}));

const { POST } = await import("./route");

function request(body?: unknown): Request {
  return new Request("http://localhost:3000/api/notifications/read", {
    method: "POST",
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
}

beforeEach(() => {
  markReadMock.mockClear();
});

describe("POST /api/notifications/read", () => {
  it("marks all as read (ids: undefined) with no body", async () => {
    markReadMock.mockResolvedValueOnce({ ok: true });

    const response = await POST(request());

    expect(markReadMock).toHaveBeenCalledWith({ ids: undefined });
    expect(response.status).toBe(204);
  });

  it("marks only the given ids", async () => {
    markReadMock.mockResolvedValueOnce({ ok: true });

    await POST(request({ ids: [1, 2, 3] }));

    expect(markReadMock).toHaveBeenCalledWith({ ids: [1, 2, 3] });
  });

  it("ignores non-numeric entries in ids and falls back to mark-all if none remain", async () => {
    markReadMock.mockResolvedValueOnce({ ok: true });

    await POST(request({ ids: ["a", 1.5, null] }));

    expect(markReadMock).toHaveBeenCalledWith({ ids: undefined });
  });

  it("treats a malformed JSON body the same as no body (mark-all)", async () => {
    markReadMock.mockResolvedValueOnce({ ok: true });

    const response = await POST(new Request("http://x", { method: "POST", body: "not json" }));

    expect(markReadMock).toHaveBeenCalledWith({ ids: undefined });
    expect(response.status).toBe(204);
  });

  it("returns 502 when the underlying call fails", async () => {
    markReadMock.mockResolvedValueOnce({ ok: false });

    const response = await POST(request());
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "mark_read_failed" });
  });
});
