// @vitest-environment node
//
// Same rationale as `../../reviews/[id]/like/route.test.ts`: `apiFetch`
// depends on `next/headers`' request-scoped `cookies()`, so it's mocked
// here. `deleteLog` (`@/lib/activity-log`) is mocked too so this file only
// exercises the route's own branching, not the dispatch already covered by
// `activity-log.test.ts`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const deleteLogMock = vi.fn();
vi.mock("@/lib/activity-log", () => ({
  deleteLog: (...args: unknown[]) => deleteLogMock(...args),
}));

const { DELETE } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(id: string) {
  return { params: Promise.resolve({ id }) };
}

beforeEach(() => {
  apiFetchMock.mockClear();
  deleteLogMock.mockClear();
});

describe("DELETE /api/log/{id}", () => {
  it.each(["not-a-number", "-1", "1.5", ""])("returns 400 for an invalid id %p", async (id) => {
    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params(id));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));

    expect(response.status).toBe(204);
  });

  it("forwards the log id and headers built from the access token", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        deleteLogMock.mockResolvedValue({ response: backendResponse(204) });
        const result = await call({ name: "fake-client" }, "the-token");
        expect(deleteLogMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          7,
        );
        return result;
      },
    );

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));
    expect(response.status).toBe(204);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the log entry doesn't exist or isn't the caller's own", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("999999"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE(new Request("http://x", { method: "DELETE" }), params("7"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "delete_log_failed" });
  });
});
