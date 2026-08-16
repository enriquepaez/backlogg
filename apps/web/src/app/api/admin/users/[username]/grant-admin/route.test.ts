// @vitest-environment node
//
// `apiFetch` depends on `next/headers`' request-scoped `cookies()` (same
// rationale as `../../../../reviews/[id]/like/route.test.ts`), so it's mocked
// directly here rather than exercised through MSW — this file only checks
// this route's own branching (X-API-Key + Bearer double gate, status
// mapping), not `apiFetch`'s refresh logic, already covered by
// `api-fetch.test.ts`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const envMock = vi.hoisted(() => ({ ADMIN_API_KEY: "s3cr3t" as string | undefined }));
vi.mock("@/lib/env", () => ({
  env: {
    get ADMIN_API_KEY() {
      if (!envMock.ADMIN_API_KEY) {
        throw new Error("Missing required environment variable: ADMIN_API_KEY");
      }
      return envMock.ADMIN_API_KEY;
    },
  },
}));

const { POST } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(username: string) {
  return { params: Promise.resolve({ username }) };
}

beforeEach(() => {
  apiFetchMock.mockClear();
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("POST /api/admin/users/[username]/grant-admin", () => {
  it("returns 503 without calling apiFetch when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;

    const response = await POST(new Request("http://x", { method: "POST" }), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("forwards the X-API-Key and the caller's Bearer token, returning the result on 200", async () => {
    const roleGrant = { username: "alice", is_admin: true };
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const postMock = vi.fn().mockResolvedValue({
          data: roleGrant,
          response: new Response(JSON.stringify(roleGrant), { status: 200 }),
        });
        const result = await call({ POST: postMock }, "the-token");
        expect(postMock).toHaveBeenCalledWith(
          "/v1/admin/users/{username}/grant-admin",
          expect.objectContaining({
            params: { header: { "x-api-key": "s3cr3t" }, path: { username: "alice" } },
            headers: { Authorization: "Bearer the-token" },
          }),
        );
        return result;
      },
    );

    const response = await POST(new Request("http://x", { method: "POST" }), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(roleGrant);
  });

  it("returns 401 when there is no valid session (even after apiFetch's own refresh attempt)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(new Request("http://x", { method: "POST" }), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 403 when the caller is authenticated but not a superadmin", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(403) });

    const response = await POST(new Request("http://x", { method: "POST" }), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body).toEqual({ error: "forbidden" });
  });

  it("returns 404 when the target user doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await POST(new Request("http://x", { method: "POST" }), params("ghost"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic 502 failure", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(new Request("http://x", { method: "POST" }), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "grant_admin_failed" });
  });
});
