// @vitest-environment node
//
// Unlike `verify/confirm` (proxied with a plain `getApiClient()` call), this
// route goes through `apiFetch` (`@/lib/api-fetch`), which reads the access
// token from the httpOnly cookie via `next/headers`' `cookies()` — a
// request-scoped API that only works inside a real Next.js request, not when
// a Route Handler is invoked directly the way `register/route.test.ts` does.
// `apiFetch` itself is therefore mocked here (its own cookie-refresh
// behavior is `session.ts`'s concern, exercised indirectly by
// `e2e/session-ux.spec.ts`); this test covers only `route.ts`'s own
// status-code translation and header-building logic.
import { describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

// `authHeader` itself is a pure function (no `next/headers`/`server-only`
// side effects), but it lives in the same module as the client-building code
// that DOES pull in `server-only` (`session.ts`), so the whole module is
// mocked here purely to dodge that import — same reasoning as
// `register/route.test.ts` mocking `@/lib/auth/session` entirely.
vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const { POST } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

describe("POST /api/auth/verify/request", () => {
  it("returns 202 when the backend accepts the request", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(202) });

    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(202);
    expect(body).toEqual({ ok: true });
  });

  it("returns 401 when there is no valid session (even after apiFetch's own refresh retry)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "verify_request_failed" });
  });

  it("attaches the access token apiFetch hands it as a Bearer Authorization header", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const backendPost = vi.fn().mockResolvedValue({ response: backendResponse(202) });
        const fakeClient = { POST: backendPost };

        const result = await call(fakeClient, "the-access-token");

        expect(backendPost).toHaveBeenCalledWith("/v1/auth/verify/request", {
          headers: { Authorization: "Bearer the-access-token" },
        });
        return result;
      },
    );

    const response = await POST();
    expect(response.status).toBe(202);
  });
});
