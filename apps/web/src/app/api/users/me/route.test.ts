// @vitest-environment node
//
// Same pattern as `src/app/api/auth/verify/request/route.test.ts`: `apiFetch`
// depends on `next/headers`' request-scoped `cookies()`, which only works
// inside a real Next.js request, so it is mocked here rather than exercised
// for real. `DELETE`'s success path also touches `next/headers` directly (to
// clear cookies), so that module is mocked too, with a minimal in-memory
// store standing in for the real cookie jar.
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const clearAuthCookiesMock = vi.fn();
vi.mock("@/lib/auth/cookies", () => ({
  clearAuthCookies: (...args: unknown[]) => clearAuthCookiesMock(...args),
}));

const fakeCookieStore = { name: "fake-cookie-store" };
vi.mock("next/headers", () => ({
  cookies: async () => fakeCookieStore,
}));

const { PATCH, DELETE } = await import("./route");

beforeEach(() => {
  apiFetchMock.mockClear();
  clearAuthCookiesMock.mockClear();
});

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function patchRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/users/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("PATCH /api/users/me", () => {
  it("returns the updated profile on a 200 from the backend", async () => {
    const updated = {
      username: "alice",
      email: "alice@example.com",
      display_name: "Alice A.",
      bio: "Hi there",
      avatar_url: null,
      email_verified: true,
    };
    apiFetchMock.mockResolvedValueOnce({ data: updated, response: backendResponse(200) });

    const response = await PATCH(
      patchRequest({ display_name: "Alice A.", bio: "Hi there", avatar_url: null }),
    );
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(updated);
  });

  it("forwards display_name/bio/avatar_url as UserUpdate to the typed client", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const backendPatch = vi.fn().mockResolvedValue({
          data: { username: "alice", email: "a@example.com", display_name: "A", bio: null, avatar_url: null, email_verified: false },
          response: backendResponse(200),
        });
        const fakeClient = { PATCH: backendPatch };

        const result = await call(fakeClient, "the-access-token");

        expect(backendPatch).toHaveBeenCalledWith("/v1/users/me", {
          body: { display_name: "A", bio: null, avatar_url: "https://example.com/a.png" },
          headers: { Authorization: "Bearer the-access-token" },
        });
        return result;
      },
    );

    const response = await PATCH(
      patchRequest({ display_name: "A", bio: null, avatar_url: "https://example.com/a.png" }),
    );
    expect(response.status).toBe(200);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await PATCH(patchRequest({ display_name: "A", bio: null, avatar_url: null }));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("propagates a 422 for a backend validation failure", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await PATCH(patchRequest({ display_name: "A", bio: null, avatar_url: null }));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("returns 400 without calling apiFetch for a malformed JSON body", async () => {
    const request = new Request("http://localhost:3000/api/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });

    const response = await PATCH(request);

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 without calling apiFetch when a field has the wrong type", async () => {
    const response = await PATCH(patchRequest({ display_name: 42, bio: null, avatar_url: null }));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await PATCH(patchRequest({ display_name: "A", bio: null, avatar_url: null }));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "update_profile_failed" });
  });
});

describe("DELETE /api/users/me", () => {
  it("clears the auth cookies and returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE();

    expect(response.status).toBe(204);
    expect(clearAuthCookiesMock).toHaveBeenCalledWith(fakeCookieStore);
  });

  it("returns 401 and leaves cookies untouched when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(clearAuthCookiesMock).not.toHaveBeenCalled();
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE();
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "delete_account_failed" });
    expect(clearAuthCookiesMock).not.toHaveBeenCalled();
  });
});
